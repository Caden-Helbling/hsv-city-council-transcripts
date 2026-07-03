#!/usr/bin/env python3
"""HSV City Council transcript pipeline: discover / fetch-audio / transcribe."""
from __future__ import annotations

import html as html_lib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import requests

CASTUS_API = "https://imd0mxanj2.execute-api.us-west-2.amazonaws.com"
LEGISTAR_API = "https://webapi.legistar.com/v1/huntsvilleal"
TIMEOUT = 60

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
