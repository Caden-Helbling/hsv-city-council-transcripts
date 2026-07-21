#!/usr/bin/env python3
"""HSV City Council transcript pipeline: discover / fetch-audio / transcribe."""
from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable

RunFn = Callable[..., Any]

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
            "has_audio_asset": False, "has_whisper": False, "has_votes": False}


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
        "has_votes": (meeting_dir / "votes.json").exists(),
    })


def _get_with_retry(url: str, session: requests.Session, *, params: Any = None,
                    stream: bool = False, attempts: int = 4, backoff: float = 2.0,
                    sleep: Callable[[float], None] | None = None) -> requests.Response:
    """GET a URL, retrying transient upstream errors before giving up.

    Legistar's API intermittently answers valid event IDs with a 404 or 5xx
    (and occasionally drops the connection). A single such blip used to fail
    the whole weekly sync, so retry transient failures with exponential
    backoff. Non-transient 4xx (e.g. 400/401/403) raise immediately.
    """
    _sleep = sleep if sleep is not None else time.sleep
    last_exc: requests.RequestException | None = None
    for attempt in range(attempts):
        try:
            resp = session.get(url, params=params, stream=stream, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            transient = status is None or status == 404 or status >= 500
            if not transient or attempt == attempts - 1:
                raise
            _sleep(backoff * 2 ** attempt)
    assert last_exc is not None  # unreachable: attempts >= 1
    raise last_exc


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
    with _get_with_retry(url, session, stream=True) as resp:
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


def _pending_slugs(meetings_dir: Path, key: str) -> list[str]:
    out: list[str] = []
    for mdir in sorted(meetings_dir.iterdir()):
        if (mdir / "meeting.json").exists() and not Manifest.load(mdir).status.get(key, False):
            out.append(mdir.name)
    return out


def fetch_audio(slugs: list[str], all_pending: bool, publish: bool, meetings_dir: Path,
                audio_dir: Path, session: requests.Session,
                run: RunFn = subprocess.run) -> int:
    if all_pending:
        slugs = _pending_slugs(meetings_dir, "has_audio_asset" if publish else "has_whisper")
    audio_dir.mkdir(parents=True, exist_ok=True)
    failures = 0
    for slug in slugs:
        try:
            manifest = Manifest.load(meetings_dir / slug)
            opus = audio_dir / f"{slug}.opus"
            if not opus.exists():
                got_asset = False
                if not publish:
                    r = run(["gh", "release", "download", manifest.audio_asset_tag,
                             "--pattern", "*.opus", "--dir", str(audio_dir)])
                    got_asset = r.returncode == 0 and opus.exists()
                if not got_asset:
                    mp4 = audio_dir / f"{slug}.mp4"
                    print(f"  downloading video for {slug} (large)...")
                    download_file(manifest.mp4_url, mp4, session)
                    r = run(["ffmpeg", "-y", "-i", str(mp4), "-vn", "-ac", "1",
                             "-ar", "16000", "-c:a", "libopus", "-b:a", "24k", str(opus)])
                    mp4.unlink(missing_ok=True)
                    if r.returncode != 0:
                        raise RuntimeError("ffmpeg failed")
            if publish:
                r = run(["gh", "release", "create", manifest.audio_asset_tag, str(opus),
                         "--title", manifest.audio_asset_tag, "--notes", manifest.mp4_url])
                if r.returncode != 0:
                    r = run(["gh", "release", "upload", manifest.audio_asset_tag,
                             str(opus), "--clobber"])
                    if r.returncode != 0:
                        raise RuntimeError("gh release create/upload failed")
                manifest.status["has_audio_asset"] = True
                manifest.save(meetings_dir / slug)
            print(f"ok: audio ready for {slug}")
        except Exception as exc:  # noqa: BLE001 — keep processing remaining meetings
            failures += 1
            print(f"FAIL: {slug}: {exc}", file=sys.stderr)
    return 1 if failures else 0


def _srt_ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def segments_to_srt(segments: list[dict]) -> str:
    blocks = [f"{i}\n{_srt_ts(s['start'])} --> {_srt_ts(s['end'])}\n{s['text'].strip()}\n"
              for i, s in enumerate(segments, start=1)]
    return "\n".join(blocks)


def transcribe(slugs: list[str], all_pending: bool, meetings_dir: Path, audio_dir: Path,
               model_name: str = "medium") -> int:
    import whisper  # heavy import — only when transcribing

    if all_pending:
        slugs = _pending_slugs(meetings_dir, "has_whisper")
    if not slugs:
        print("nothing to transcribe")
        return 0
    import torch  # provided by whisper; used only for device selection
    if sys.platform == "darwin":
        device = "mps"
    elif torch.cuda.is_available():
        device = "cuda"  # e.g. desktop-6npd885's GTX 1080 Ti
    else:
        device = "cpu"
    fp16 = device == "cuda"  # half precision on CUDA; fp32 elsewhere
    print(f"whisper {model_name} on {device}")
    model = whisper.load_model(model_name, device=device)
    failures = 0
    for slug in slugs:  # serial — GPU does not parallelize across meetings
        try:
            audio_path = audio_dir / f"{slug}.opus"
            if not audio_path.exists():
                raise FileNotFoundError(f"{audio_path} missing — run fetch-audio first")
            print(f"transcribing {slug} (this takes a while)...")
            result = model.transcribe(str(audio_path), language="en", fp16=fp16)
            tdir = meetings_dir / slug / "transcript"
            tdir.mkdir(parents=True, exist_ok=True)
            (tdir / f"whisper-{model_name}.txt").write_text(result["text"].strip() + "\n")
            (tdir / f"whisper-{model_name}.srt").write_text(segments_to_srt(result["segments"]))
            manifest = Manifest.load(meetings_dir / slug)
            recompute_status(meetings_dir / slug, manifest)
            manifest.save(meetings_dir / slug)
            print(f"ok: transcribed {slug}")
        except Exception as exc:  # noqa: BLE001 — keep processing remaining meetings
            failures += 1
            print(f"FAIL: {slug}: {exc}", file=sys.stderr)
    return 1 if failures else 0


# ---- votes: resolve a Resolution/Ordinance number to its council roll-call ----

_NUM_RE = re.compile(r"No\.\s*(\d{2}-\d+)")
_AYE_RE = re.compile(r"Aye:\s*(.+)")
_NAY_RE = re.compile(r"Nay:\s*(.+)")


@dataclass
class RollCall:
    consent: bool
    aye: list[str]
    nay: list[str]


def find_matter(number: str, session: requests.Session) -> dict | None:
    """Find a Legistar matter by its adopted Resolution/Ordinance number (e.g. '23-689').

    Huntsville stores the number inside MatterTitle ('...Resolution No. 23-689'),
    not in a structured field, so we filter on the substring then confirm by regex.
    """
    resp = session.get(f"{LEGISTAR_API}/matters",
                       params={"$filter": f"substringof('No. {number}',MatterTitle)"},
                       timeout=TIMEOUT)
    resp.raise_for_status()
    matters = resp.json()
    if not isinstance(matters, list):
        raise ValueError(f"unexpected Legistar matters shape: {type(matters)}")
    exact = re.compile(rf"No\.\s*{re.escape(number)}\b")
    for m in matters:
        if exact.search(m.get("MatterTitle") or ""):
            return m
    return matters[0] if matters else None


def matter_action(matter_id: int, session: requests.Session) -> dict | None:
    resp = session.get(f"{LEGISTAR_API}/matters/{matter_id}/histories", timeout=TIMEOUT)
    resp.raise_for_status()
    hist = resp.json()
    if not isinstance(hist, list) or not hist:
        return None
    passed = [h for h in hist if h.get("MatterHistoryPassedFlagName")]
    return passed[-1] if passed else hist[-1]


def find_regular_event(day: str, session: requests.Session) -> dict | None:
    resp = session.get(f"{LEGISTAR_API}/events",
                       params={"$filter": f"EventDate eq datetime'{day}T00:00:00'"},
                       timeout=TIMEOUT)
    resp.raise_for_status()
    events = resp.json()
    if not isinstance(events, list) or not events:
        return None
    for e in events:
        if "regular" in (e.get("EventBodyName") or "").lower():
            return e
    return events[0]


def _pdf_text(path: Path, run: RunFn = subprocess.run) -> str | None:
    """Best-effort PDF -> text: pdftotext if present, else pypdf/PyPDF2. None if all fail."""
    try:
        r = run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True)
        if getattr(r, "returncode", 1) == 0 and (r.stdout or "").strip():
            return r.stdout
    except FileNotFoundError:
        pass
    for mod in ("pypdf", "PyPDF2"):
        try:
            reader = __import__(mod).PdfReader(str(path))
            return "\n".join((p.extract_text() or "") for p in reader.pages)
        except Exception:  # noqa: BLE001 — try the next backend
            continue
    return None


def _names(line: str) -> list[str]:
    line = re.sub(r"\band\b", ",", line.split("\n", 1)[0])
    out = [n.strip() for n in line.split(",")]
    return [n for n in out if n and n.lower() != "none"]


def parse_minutes_rollcall(text: str, number: str) -> RollCall | None:
    """Return the roll-call governing item `number` in `text` (minutes body).

    Handles both Huntsville patterns: an item voted individually (its own
    'moved to approve ... Aye: ... Nay: ...' right after it) and an item swept
    into the Consent Agenda (a single earlier 'to approve the Consent Agenda ...
    Aye: ...' motion). Returns None if no roll-call is recorded (voice/draft).
    """
    idx = text.find(f"No. {number}")
    if idx < 0:
        return None
    nxt = _NUM_RE.search(text, idx + 4)
    window = text[idx: nxt.start() if nxt else len(text)]
    if re.search(r"moved\s+to\s+approve", window) and _AYE_RE.search(window):
        aye = _AYE_RE.search(window)
        nay = _NAY_RE.search(window)
        return RollCall(False, _names(aye.group(1)), _names(nay.group(1)) if nay else [])
    consent_at = None
    for m in re.finditer(r"approve\s+the\s+Consent\s+Agenda", text[:idx]):
        consent_at = m.start()
    if consent_at is None:
        return None
    tail = text[consent_at:]
    aye = _AYE_RE.search(tail)
    if not aye:
        return None
    nay = _NAY_RE.search(tail)
    return RollCall(True, _names(aye.group(1)), _names(nay.group(1)) if nay else [])


def extract_minutes_votes(text: str) -> list[dict]:
    """Every Resolution/Ordinance number in minutes order, each with its roll-call.

    `vote` is None when the minutes record no roll-call for the item
    (voice vote, Draft minutes, or an item merely presented).
    """
    items: list[dict] = []
    seen: set[str] = set()
    for m in _NUM_RE.finditer(text):
        number = m.group(1)
        if number in seen:
            continue
        seen.add(number)
        rc = parse_minutes_rollcall(text, number)
        items.append({"number": number, "vote": asdict(rc) if rc else None})
    return items


def extract_votes(slugs: list[str], meetings_dir: Path, session: requests.Session) -> int:
    if not slugs:
        slugs = [d.name for d in sorted(meetings_dir.iterdir())
                 if (d / "meeting.json").exists()]
    failures = 0
    for slug in slugs:
        try:
            mdir = meetings_dir / slug
            manifest = Manifest.load(mdir)
            # pick up late-published minutes from Legistar
            minutes_status = None
            if not manifest.minutes_url and manifest.legistar_event_id:
                # Best-effort: a flaky Legistar lookup must not fail the sync.
                try:
                    resp = _get_with_retry(
                        f"{LEGISTAR_API}/events/{manifest.legistar_event_id}", session)
                except requests.RequestException as exc:
                    print(f"skip: {slug}: Legistar unreachable for late minutes "
                          f"({exc}); will retry next run", file=sys.stderr)
                    continue
                event = resp.json()
                manifest.minutes_url = event.get("EventMinutesFile")
                minutes_status = event.get("EventMinutesStatusName")
            if manifest.minutes_url and not (mdir / "minutes.pdf").exists():
                download_file(manifest.minutes_url, mdir / "minutes.pdf", session)
            if not (mdir / "minutes.pdf").exists():
                detail = f" (Legistar status: {minutes_status})" if minutes_status else ""
                print(f"skip: {slug}: no minutes PDF published yet{detail}")
                recompute_status(mdir, manifest)
                manifest.save(mdir)
                continue
            text = _pdf_text(mdir / "minutes.pdf")
            if text is None:
                raise RuntimeError("could not extract text from minutes.pdf")
            items = extract_minutes_votes(text)
            (mdir / "votes.json").write_text(json.dumps(
                {"slug": slug, "date": manifest.date,
                 "minutes_url": manifest.minutes_url, "items": items},
                indent=2) + "\n")
            recompute_status(mdir, manifest)
            manifest.save(mdir)
            recorded = sum(1 for i in items if i["vote"])
            print(f"ok: {slug}: {len(items)} items, {recorded} with roll-calls -> votes.json")
        except Exception as exc:  # noqa: BLE001 — keep processing remaining meetings
            failures += 1
            print(f"FAIL: {slug}: {exc}", file=sys.stderr)
    return 1 if failures else 0


def votes(number: str, session: requests.Session, meetings_dir: Path) -> int:
    number = number.strip()
    matter = find_matter(number, session)
    if not matter:
        print(f"no Legistar matter found for No. {number}", file=sys.stderr)
        return 1
    mid = matter["MatterId"]
    title = re.sub(r"\s+", " ", (matter.get("MatterTitle") or "")).strip()
    print(f"Resolution/Ordinance No. {number}  (Matter {mid}, file {matter.get('MatterFile')})")
    print(f"  {title[:200]}")
    action = matter_action(mid, session)
    day = ((action or {}).get("MatterHistoryActionDate")
           or matter.get("MatterPassedDate") or "")[:10]
    if action:
        print(f"  action: {action.get('MatterHistoryActionName')} "
              f"({action.get('MatterHistoryPassedFlagName')})  "
              f"mover: {action.get('MatterHistoryMoverName')}  "
              f"second: {action.get('MatterHistorySeconderName')}  ({day})")
    event = find_regular_event(day, session) if day else None
    minutes_url = (event or {}).get("EventMinutesFile")
    if minutes_url:
        print(f"  minutes: {minutes_url}")
    text = None
    for mdir in sorted(meetings_dir.glob(f"{day}*")) if day else []:
        if (mdir / "minutes.pdf").exists():
            text = _pdf_text(mdir / "minutes.pdf")
            break
    if text is None and minutes_url:
        try:
            tmp = Path(tempfile.gettempdir()) / f"hsvcc_minutes_{day}.pdf"
            download_file(minutes_url, tmp, session)
            text = _pdf_text(tmp)
        except Exception as exc:  # noqa: BLE001 — minutes are best-effort
            print(f"  warn: could not fetch/parse minutes: {exc}")
    if text:
        rc = parse_minutes_rollcall(text, number)
        if rc:
            kind = "CONSENT AGENDA (no separate vote/debate)" if rc.consent else "individual roll-call"
            print(f"  vote [{kind}]:")
            print(f"    Aye: {', '.join(rc.aye) if rc.aye else '—'}")
            print(f"    Nay: {', '.join(rc.nay) if rc.nay else 'None'}")
        else:
            print("  (no roll-call recorded in minutes — likely a voice vote or Draft minutes)")
    else:
        print("  (no machine-readable minutes available; see minutes URL above)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hsvcc", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_disc = sub.add_parser("discover", help="find meetings, fetch agendas + captions")
    p_disc.add_argument("--since", type=date.fromisoformat, default=date(2026, 4, 1))
    p_audio = sub.add_parser("fetch-audio", help="get audio (release asset or MP4+ffmpeg)")
    p_audio.add_argument("slugs", nargs="*")
    p_audio.add_argument("--all-pending", action="store_true")
    p_audio.add_argument("--publish", action="store_true",
                         help="extract from MP4 and upload as GitHub release asset (CI)")
    p_tr = sub.add_parser("transcribe", help="run Whisper on fetched audio")
    p_tr.add_argument("slugs", nargs="*")
    p_tr.add_argument("--all-pending", action="store_true")
    p_tr.add_argument("--model", default="medium")
    p_votes = sub.add_parser(
        "votes", help="show the council roll-call for a Resolution/Ordinance number")
    p_votes.add_argument("number", help="adopted number, e.g. 23-689")
    p_ev = sub.add_parser(
        "extract-votes", help="parse each meeting's minutes into votes.json")
    p_ev.add_argument("slugs", nargs="*", help="meeting slugs (default: all meetings)")
    args = parser.parse_args(argv)
    session = requests.Session()
    session.headers["User-Agent"] = "hsv-city-council-transcripts (personal archival tool)"
    if args.command == "discover":
        return 1 if discover(args.since, MEETINGS_DIR, session) else 0
    if args.command == "fetch-audio":
        return fetch_audio(args.slugs, args.all_pending, args.publish,
                           MEETINGS_DIR, AUDIO_DIR, session)
    if args.command == "transcribe":
        return transcribe(args.slugs, args.all_pending, MEETINGS_DIR, AUDIO_DIR,
                          model_name=args.model)
    if args.command == "votes":
        return votes(args.number, session, MEETINGS_DIR)
    if args.command == "extract-votes":
        return extract_votes(args.slugs, MEETINGS_DIR, session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
