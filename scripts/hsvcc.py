#!/usr/bin/env python3
"""HSV City Council transcript pipeline: discover / fetch-audio / transcribe."""
from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import requests

CASTUS_API = "https://imd0mxanj2.execute-api.us-west-2.amazonaws.com"
LEGISTAR_API = "https://webapi.legistar.com/v1/huntsvilleal"
ARCHIVE_URL = "https://www.huntsvilleal.gov/videocategory/city-council-meetings/"
TIMEOUT = 60
REPO_ROOT = Path(__file__).resolve().parent.parent
MEETINGS_DIR = REPO_ROOT / "meetings"
AUDIO_DIR = REPO_ROOT / "audio"

_TS_RE = re.compile(r"(?:(\d+):)?(\d+):(\d+)\.(\d+)\s*-->")

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], start=1)}

_VIDEO_LINK_RE = re.compile(r'href="(https://www\.huntsvilleal\.gov/videos/[^"]+/)"')
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
_CASTUS_RE = re.compile(r"cloud\.castus\.tv/vod/hsv-tv/embed/([a-f0-9]+)")
_SLUG_DATE_RE = re.compile(
    r"(january|february|march|april|may|june|july|august|september|october|november|december)"
    r"-(\d{1,2})-(\d{4})")


def parse_archive_page(html: str) -> list[str]:
    seen: list[str] = []
    for m in _VIDEO_LINK_RE.finditer(html):
        url = m.group(1)
        if url not in seen:
            seen.append(url)
    return seen


def parse_video_page(html: str) -> tuple[str, str]:
    h1 = _H1_RE.search(html)
    castus = _CASTUS_RE.search(html)
    if not h1 or not castus:
        raise ValueError("video page missing h1 title or castus embed")
    title = html_lib.unescape(re.sub(r"<[^>]+>", "", h1.group(1))).strip()
    return title, castus.group(1)


def date_from_slug(url: str) -> date | None:
    m = _SLUG_DATE_RE.search(url)
    if not m:
        return None
    return date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))


def _default_status() -> dict[str, bool]:
    return {"has_agenda": False, "has_minutes": False, "has_captions": False,
            "has_audio_asset": False, "has_whisper": False}


@dataclass
class Manifest:
    slug: str
    title: str
    date: str
    body: str | None
    video_page_url: str
    castus_id: str
    mp4_url: str
    legistar_event_id: int | None
    legistar_url: str | None
    agenda_url: str | None
    minutes_url: str | None
    audio_asset_tag: str
    status: dict[str, bool] = field(default_factory=_default_status)

    @classmethod
    def load(cls, meeting_dir: Path) -> "Manifest":
        return cls(**json.loads((meeting_dir / "meeting.json").read_text()))

    def save(self, meeting_dir: Path) -> None:
        meeting_dir.mkdir(parents=True, exist_ok=True)
        (meeting_dir / "meeting.json").write_text(json.dumps(asdict(self), indent=2) + "\n")


def recompute_status(meeting_dir: Path, manifest: Manifest) -> None:
    manifest.status.update({
        "has_agenda": (meeting_dir / "agenda.pdf").exists(),
        "has_minutes": (meeting_dir / "minutes.pdf").exists(),
        "has_captions": (meeting_dir / "captions.vtt").exists(),
        "has_whisper": (meeting_dir / "transcript" / "whisper-medium.txt").exists(),
    })


def resolve_mp4_url(castus_id: str, session: requests.Session) -> str:
    resp = session.post(f"{CASTUS_API}/upload/get",
                        json={"file": castus_id, "type": "vod", "user": ""}, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    url = data.get("response", {}).get("payload", {}).get("data")
    if not isinstance(url, str) or not url.startswith("http"):
        raise ValueError(f"unexpected Castus upload/get shape for {castus_id}: {data}")
    return url.split("?")[0]


def fetch_captions(castus_id: str, session: requests.Session) -> str | None:
    try:
        resp = session.post(f"{CASTUS_API}/upload/get-captions",
                            json={"file": {"_id": castus_id}, "user": {"_id": ""}}, timeout=TIMEOUT)
        resp.raise_for_status()
        url = resp.json().get("response", {}).get("payload")
        if not isinstance(url, str) or not url.startswith("http"):
            return None
        vtt = session.get(url, timeout=TIMEOUT)
        vtt.raise_for_status()
        return vtt.text if vtt.text.lstrip().startswith("WEBVTT") else None
    except Exception as exc:  # noqa: BLE001 — captions are best-effort
        print(f"  warn: captions unavailable for {castus_id}: {exc}")
        return None


def fetch_legistar_events(since: date, session: requests.Session) -> list[dict]:
    resp = session.get(
        f"{LEGISTAR_API}/events",
        params={"$filter": f"EventDate ge datetime'{since.isoformat()}T00:00:00'",
                "$orderby": "EventDate asc"},
        timeout=TIMEOUT)
    resp.raise_for_status()
    events = resp.json()
    if not isinstance(events, list):
        raise ValueError(f"unexpected Legistar events shape: {type(events)}")
    return events


def match_event(meeting_date: date, title: str, events: list[dict]) -> dict | None:
    same_day = [e for e in events if e.get("EventDate", "").startswith(meeting_date.isoformat())]
    if not same_day:
        return None
    if len(same_day) == 1:
        return same_day[0]
    title_l = title.lower()
    for keyword in ("work session", "special"):
        if keyword in title_l:
            for e in same_day:
                if keyword in e.get("EventBodyName", "").lower():
                    return e
    for e in same_day:
        if "regular" in e.get("EventBodyName", "").lower():
            return e
    return same_day[0]


def meeting_slug(title: str, meeting_date: date) -> str:
    base = re.split(r"[–—-]\s*(january|february|march|april|may|june|july|august|"
                    r"september|october|november|december)", title, flags=re.I)[0]
    base = re.sub(r"^huntsville\s+", "", base.strip().lower())
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return f"{meeting_date.isoformat()}-{base}"


@dataclass
class Cue:
    start: float
    text: str


def _ts_to_seconds(m: re.Match[str]) -> float:
    hours = int(m.group(1) or 0)
    return hours * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1000


def _seconds_to_ts(s: float) -> str:
    n = int(s)
    return f"{n // 3600:02d}:{n % 3600 // 60:02d}:{n % 60:02d}"


def iter_archive_video_urls(session: requests.Session, since: date) -> list[str]:
    urls: list[str] = []
    page = 1
    while True:
        page_url = ARCHIVE_URL if page == 1 else f"{ARCHIVE_URL}page/{page}/"
        resp = session.get(page_url, timeout=TIMEOUT)
        if resp.status_code == 404:
            break
        resp.raise_for_status()
        links = parse_archive_page(resp.text)
        if not links:
            break
        urls.extend(u for u in links if u not in urls)
        dated = [d for u in links if (d := date_from_slug(u)) is not None]
        if dated and max(dated) < since:
            break
        page += 1
    return urls


def download_file(url: str, dest: Path, session: requests.Session) -> None:
    with session.get(url, stream=True, timeout=TIMEOUT) as resp:
        resp.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                fh.write(chunk)


def _discover_one(url: str, events: list[dict], meetings_dir: Path,
                  session: requests.Session) -> None:
    resp = session.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    title, castus_id = parse_video_page(resp.text)
    meeting_date = date_from_slug(url)
    if meeting_date is None:
        raise ValueError(f"cannot parse date from slug: {url}")
    slug = meeting_slug(title, meeting_date)
    mdir = meetings_dir / slug
    if (mdir / "meeting.json").exists():
        manifest = Manifest.load(mdir)
    else:
        event = match_event(meeting_date, title, events)
        if event is None:
            print(f"  warn: no Legistar event for {slug}")
        manifest = Manifest(
            slug=slug, title=title, date=meeting_date.isoformat(),
            body=event.get("EventBodyName") if event else None,
            video_page_url=url, castus_id=castus_id,
            mp4_url=resolve_mp4_url(castus_id, session),
            legistar_event_id=event.get("EventId") if event else None,
            legistar_url=event.get("EventInSiteURL") if event else None,
            agenda_url=event.get("EventAgendaFile") if event else None,
            minutes_url=event.get("EventMinutesFile") if event else None,
            audio_asset_tag=f"audio-{slug}",
        )
    # pick up late-published minutes from Legistar on re-runs
    if manifest.legistar_event_id and not manifest.minutes_url:
        event = next((e for e in events if e.get("EventId") == manifest.legistar_event_id), None)
        if event and event.get("EventMinutesFile"):
            manifest.minutes_url = event["EventMinutesFile"]
    if manifest.agenda_url and not (mdir / "agenda.pdf").exists():
        download_file(manifest.agenda_url, mdir / "agenda.pdf", session)
    if manifest.minutes_url and not (mdir / "minutes.pdf").exists():
        download_file(manifest.minutes_url, mdir / "minutes.pdf", session)
    if not (mdir / "captions.vtt").exists():
        vtt = fetch_captions(castus_id, session)
        if vtt:
            mdir.mkdir(parents=True, exist_ok=True)
            (mdir / "captions.vtt").write_text(vtt)
            (mdir / "captions.txt").write_text(render_captions_txt(vtt))
    recompute_status(mdir, manifest)
    manifest.save(mdir)


def discover(since: date, meetings_dir: Path, session: requests.Session) -> int:
    events = fetch_legistar_events(since, session)
    failures = 0
    for url in iter_archive_video_urls(session, since):
        d = date_from_slug(url)
        if d is None or d < since:
            continue
        try:
            _discover_one(url, events, meetings_dir, session)
            print(f"ok: {url}")
        except Exception as exc:  # noqa: BLE001 — one bad meeting must not kill the batch
            failures += 1
            print(f"FAIL: {url}: {exc}", file=sys.stderr)
    return failures


def parse_vtt(content: str) -> list[Cue]:
    cues: list[Cue] = []
    for block in re.split(r"\n{2,}", content.strip()):
        m = _TS_RE.search(block)
        if not m:
            continue
        text_lines = block[m.end():].splitlines()
        # first "line" is the remainder of the timing line; cue text follows
        text = " ".join(line.strip() for line in text_lines[1:] if line.strip())
        if not text:
            continue
        cues.append(Cue(start=_ts_to_seconds(m), text=text))
    return cues


def render_captions_txt(vtt: str, marker_interval: float = 300.0) -> str:
    lines: list[str] = []
    next_marker = 0.0
    prev_text: str | None = None
    for cue in parse_vtt(vtt):
        if cue.start >= next_marker:
            lines.append(f"\n[{_seconds_to_ts(cue.start)}]")
            next_marker = (cue.start // marker_interval + 1) * marker_interval
        if cue.text != prev_text:
            lines.append(cue.text)
            prev_text = cue.text
    return "\n".join(lines).strip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hsvcc", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_disc = sub.add_parser("discover", help="find meetings, fetch agendas + captions")
    p_disc.add_argument("--since", type=date.fromisoformat, default=date(2026, 4, 1))
    args = parser.parse_args(argv)
    session = requests.Session()
    session.headers["User-Agent"] = "hsv-city-council-transcripts (personal archival tool)"
    if args.command == "discover":
        return 1 if discover(args.since, MEETINGS_DIR, session) else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
