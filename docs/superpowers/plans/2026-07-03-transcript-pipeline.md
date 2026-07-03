# HSV City Council Transcript Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LLM-free pipeline that collects Huntsville City Council meeting videos, official captions, agendas, and Whisper transcripts into per-meeting folders, with a scheduled GitHub Action for the cheap parts.

**Architecture:** Single typed Python CLI (`scripts/hsvcc.py`) with three subcommands (`discover`, `fetch-audio`, `transcribe`). Pure parsing functions are unit-tested against recorded fixtures; network and subprocess calls are thin, mockable wrappers. A weekly GitHub Action runs `discover`, commits artifacts, and publishes extracted audio as release assets.

**Tech Stack:** Python 3.10+, `requests` (only pipeline dep), `pytest` (dev), `openai-whisper` (local transcription only), ffmpeg, GitHub CLI (`gh`), GitHub Actions.

## Global Constraints

- Python 3.10+ with full type hints on all functions (user preference).
- `requests` is the ONLY required runtime dependency; whisper/torch imported lazily inside `transcribe` only.
- No LLM calls anywhere in the pipeline.
- Meeting folders: `meetings/<YYYY-MM-DD>-<slug>/` per spec schema in `docs/superpowers/specs/2026-07-03-transcript-pipeline-design.md`.
- All network parse points assert response shape with clear error messages.
- Per-meeting failures warn and continue; process exits non-zero if any meeting failed.
- Conventional commits, imperative subject.
- `.gitignore` must cover `audio/`, `*.mp4`, `CLAUDE.md`, `.claude/`, `status.md`, `__pycache__/`.

---

### Task 1: Scaffolding + VTT renderer

**Files:**
- Create: `.gitignore`, `requirements.txt`, `requirements-dev.txt`, `pytest.ini`, `tests/conftest.py`, `scripts/hsvcc.py`, `tests/test_vtt.py`

**Interfaces:**
- Produces: `parse_vtt(content: str) -> list[Cue]` where `Cue` is `@dataclass` with `start: float`, `text: str`; `render_captions_txt(vtt: str, marker_interval: float = 300.0) -> str`.

- [ ] **Step 1: Write scaffolding files**

`.gitignore`:
```gitignore
audio/
*.mp4
*.opus
__pycache__/
.pytest_cache/

# Personal AI / agent context — scratch space for individual contributors.
CLAUDE.md
.claude/
status.md
```

`requirements.txt`:
```
requests>=2.31
```

`requirements-dev.txt`:
```
-r requirements.txt
pytest>=8
```

`pytest.ini`:
```ini
[pytest]
testpaths = tests
```

`tests/conftest.py`:
```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
```

- [ ] **Step 2: Write failing VTT tests** (`tests/test_vtt.py`)

```python
from hsvcc import Cue, parse_vtt, render_captions_txt

SAMPLE = """WEBVTT

00:01:00.250 --> 00:01:01.680
Good evening everyone.

00:01:02.450 --> 00:01:06.809
It is Thursday, June 25th.

00:01:02.450 --> 00:01:06.809
It is Thursday, June 25th.

01:02:03.000 --> 01:02:04.000
Much later cue.
"""


def test_parse_vtt_extracts_cues() -> None:
    cues = parse_vtt(SAMPLE)
    assert cues[0] == Cue(start=60.25, text="Good evening everyone.")
    assert len(cues) == 4
    assert cues[3].start == 3723.0


def test_parse_vtt_handles_mm_ss_timestamps() -> None:
    cues = parse_vtt("WEBVTT\n\n01:00.500 --> 01:02.000\nHi.\n")
    assert cues == [Cue(start=60.5, text="Hi.")]


def test_render_dedups_and_adds_markers() -> None:
    out = render_captions_txt(SAMPLE)
    assert out.count("It is Thursday, June 25th.") == 1
    assert "[00:01:00]" in out
    assert "[01:02:03]" in out
```

- [ ] **Step 3: Run tests, verify failure** — `python3 -m pytest tests/test_vtt.py -v` → FAIL (ImportError).

- [ ] **Step 4: Implement in `scripts/hsvcc.py`**

```python
#!/usr/bin/env python3
"""HSV City Council transcript pipeline: discover / fetch-audio / transcribe."""
from __future__ import annotations

import re
from dataclasses import dataclass

_TS_RE = re.compile(r"(?:(\d+):)?(\d+):(\d+)\.(\d+)\s*-->")


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
        # drop remainder of the timing line, keep cue text lines
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
```

Note the timing-line handling: `block[m.end():]` starts right after `-->`; `text_lines[1:]` skips the end-timestamp remainder.

- [ ] **Step 5: Run tests, verify pass** — `python3 -m pytest tests/test_vtt.py -v` → 3 PASS.

- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat: scaffold repo and add VTT parsing/rendering"`

---

### Task 2: HTML parsers (archive page, video page, dates, slugs)

**Files:**
- Create: `tests/fixtures/archive-page-1.html`, `tests/fixtures/video-page.html`, `tests/test_parsers.py`
- Modify: `scripts/hsvcc.py`

**Interfaces:**
- Produces: `parse_archive_page(html: str) -> list[str]` (video page URLs, deduped, no bare `/videos/`); `parse_video_page(html: str) -> tuple[str, str]` returning `(title, castus_id)`; `date_from_slug(url: str) -> date | None`; `meeting_slug(title: str, meeting_date: date) -> str`.

- [ ] **Step 1: Record fixtures**

```bash
curl -s 'https://www.huntsvilleal.gov/videocategory/city-council-meetings/' -o tests/fixtures/archive-page-1.html
curl -s 'https://www.huntsvilleal.gov/videos/huntsville-city-council-meeting-june-25-2026-2/' -o tests/fixtures/video-page.html
```

- [ ] **Step 2: Write failing tests** (`tests/test_parsers.py`)

```python
from datetime import date
from pathlib import Path

from hsvcc import date_from_slug, meeting_slug, parse_archive_page, parse_video_page

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_archive_page_finds_video_links() -> None:
    links = parse_archive_page((FIXTURES / "archive-page-1.html").read_text())
    assert "https://www.huntsvilleal.gov/videos/huntsville-city-council-meeting-june-25-2026-2/" in links
    assert all(link.rstrip("/") != "https://www.huntsvilleal.gov/videos" for link in links)
    assert len(links) == len(set(links))


def test_parse_video_page_extracts_title_and_castus_id() -> None:
    title, castus_id = parse_video_page((FIXTURES / "video-page.html").read_text())
    assert title == "Huntsville City Council Meeting – June 25, 2026"
    assert castus_id == "6a3dcff79537260002c64cd9"


def test_date_from_slug() -> None:
    assert date_from_slug(
        "https://www.huntsvilleal.gov/videos/huntsville-city-council-meeting-june-25-2026-2/"
    ) == date(2026, 6, 25)
    assert date_from_slug("https://www.huntsvilleal.gov/videos/some-video-without-date/") is None


def test_meeting_slug() -> None:
    assert meeting_slug("Huntsville City Council Meeting – June 25, 2026", date(2026, 6, 25)) == \
        "2026-06-25-city-council-meeting"
```

- [ ] **Step 3: Run, verify FAIL** — `python3 -m pytest tests/test_parsers.py -v`

- [ ] **Step 4: Implement in `scripts/hsvcc.py`**

```python
import html as html_lib
from datetime import date

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


def meeting_slug(title: str, meeting_date: date) -> str:
    base = re.split(r"[–—-]\s*(january|february|march|april|may|june|july|august|"
                    r"september|october|november|december)", title, flags=re.I)[0]
    base = re.sub(r"^huntsville\s+", "", base.strip().lower())
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return f"{meeting_date.isoformat()}-{base}"
```

- [ ] **Step 5: Run, verify PASS** — `python3 -m pytest tests/test_parsers.py -v`

- [ ] **Step 6: Commit** — `git commit -m "feat: add archive/video page parsers and slug helpers"`

---

### Task 3: Castus + Legistar API clients

**Files:**
- Create: `tests/test_clients.py`
- Modify: `scripts/hsvcc.py`

**Interfaces:**
- Produces: `resolve_mp4_url(castus_id: str, session: requests.Session) -> str` (unsigned URL, query stripped); `fetch_captions(castus_id: str, session: requests.Session) -> str | None` (VTT text or None); `fetch_legistar_events(since: date, session: requests.Session) -> list[dict]`; `match_event(meeting_date: date, title: str, events: list[dict]) -> dict | None`.

- [ ] **Step 1: Write failing tests** (`tests/test_clients.py`) using a fake session:

```python
from datetime import date
from typing import Any

from hsvcc import fetch_captions, fetch_legistar_events, match_event, resolve_mp4_url


class FakeResponse:
    def __init__(self, payload: Any, text: str = "") -> None:
        self._payload = payload
        self.text = text
        self.status_code = 200

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        pass


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, Any]] = []

    def post(self, url: str, json: Any = None, timeout: int = 0) -> FakeResponse:
        self.calls.append(("post", url, json))
        return self.responses.pop(0)

    def get(self, url: str, params: Any = None, timeout: int = 0) -> FakeResponse:
        self.calls.append(("get", url, params))
        return self.responses.pop(0)


def test_resolve_mp4_url_strips_query() -> None:
    s = FakeSession([FakeResponse(
        {"response": {"success": True, "payload": {"data": "https://cdn/x.mp4?sig=1"}}})])
    assert resolve_mp4_url("abc", s) == "https://cdn/x.mp4"
    assert s.calls[0][2] == {"file": "abc", "type": "vod", "user": ""}


def test_fetch_captions_returns_vtt_text() -> None:
    s = FakeSession([
        FakeResponse({"response": {"payload": "https://s3/abc.vtt?sig"}}),
        FakeResponse(None, text="WEBVTT\n\n00:00.0 --> 00:01.0\nHi\n"),
    ])
    vtt = fetch_captions("abc", s)
    assert vtt is not None and vtt.startswith("WEBVTT")


def test_fetch_captions_none_on_error() -> None:
    class Boom(FakeSession):
        def post(self, url: str, json: Any = None, timeout: int = 0) -> FakeResponse:
            raise RuntimeError("api down")
    assert fetch_captions("abc", Boom([])) is None


def test_fetch_legistar_events_filters_since() -> None:
    s = FakeSession([FakeResponse([{"EventId": 1}])])
    events = fetch_legistar_events(date(2026, 4, 1), s)
    assert events == [{"EventId": 1}]
    assert "2026-04-01" in str(s.calls[0][2])


EVENTS = [
    {"EventId": 1, "EventDate": "2026-06-25T00:00:00", "EventBodyName": "City Council Regular Meeting"},
    {"EventId": 2, "EventDate": "2026-06-25T00:00:00", "EventBodyName": "City Council Work Session"},
    {"EventId": 3, "EventDate": "2026-06-11T00:00:00", "EventBodyName": "City Council Regular Meeting"},
]


def test_match_event_by_date_and_body() -> None:
    ev = match_event(date(2026, 6, 25), "Huntsville City Council Work Session – June 25, 2026", EVENTS)
    assert ev is not None and ev["EventId"] == 2


def test_match_event_prefers_regular_meeting() -> None:
    ev = match_event(date(2026, 6, 25), "Huntsville City Council Meeting – June 25, 2026", EVENTS)
    assert ev is not None and ev["EventId"] == 1


def test_match_event_none_when_no_date_match() -> None:
    assert match_event(date(2026, 6, 1), "Joint Work Session", EVENTS) is None
```

- [ ] **Step 2: Run, verify FAIL.**

- [ ] **Step 3: Implement in `scripts/hsvcc.py`**

```python
from typing import Any

import requests

CASTUS_API = "https://imd0mxanj2.execute-api.us-west-2.amazonaws.com"
LEGISTAR_API = "https://webapi.legistar.com/v1/huntsvilleal"
TIMEOUT = 60


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
```

- [ ] **Step 4: Run all tests, verify PASS** — `python3 -m pytest -v`

- [ ] **Step 5: Commit** — `git commit -m "feat: add Castus and Legistar API clients with matching"`

---

### Task 4: Manifest model + status recomputation

**Files:**
- Create: `tests/test_manifest.py`
- Modify: `scripts/hsvcc.py`

**Interfaces:**
- Produces: `@dataclass Manifest` (fields exactly per spec schema; `status: dict[str, bool]`); `Manifest.load(meeting_dir: Path) -> Manifest`; `Manifest.save(meeting_dir: Path) -> None` (writes `meeting.json`, 2-space indent, trailing newline); `recompute_status(meeting_dir: Path, manifest: Manifest) -> None` (mutates `manifest.status` from files on disk; `has_audio_asset` preserved as-is).

- [ ] **Step 1: Write failing tests** (`tests/test_manifest.py`)

```python
from pathlib import Path

from hsvcc import Manifest, recompute_status


def make_manifest() -> Manifest:
    return Manifest(
        slug="2026-06-25-city-council-meeting",
        title="Huntsville City Council Meeting – June 25, 2026",
        date="2026-06-25",
        body="City Council Regular Meeting",
        video_page_url="https://www.huntsvilleal.gov/videos/x/",
        castus_id="abc",
        mp4_url="https://cdn/x.mp4",
        legistar_event_id=1223,
        legistar_url="https://huntsvilleal.legistar.com/MeetingDetail.aspx?LEGID=1223",
        agenda_url="https://cdn/agenda.pdf",
        minutes_url=None,
        audio_asset_tag="audio-2026-06-25-city-council-meeting",
    )


def test_manifest_round_trip(tmp_path: Path) -> None:
    m = make_manifest()
    m.save(tmp_path)
    loaded = Manifest.load(tmp_path)
    assert loaded == m
    assert (tmp_path / "meeting.json").read_text().endswith("\n")


def test_recompute_status_from_disk(tmp_path: Path) -> None:
    m = make_manifest()
    m.status["has_audio_asset"] = True
    (tmp_path / "agenda.pdf").write_bytes(b"%PDF")
    (tmp_path / "captions.vtt").write_text("WEBVTT\n")
    (tmp_path / "transcript").mkdir()
    (tmp_path / "transcript" / "whisper-medium.txt").write_text("hi")
    recompute_status(tmp_path, m)
    assert m.status == {"has_agenda": True, "has_minutes": False, "has_captions": True,
                        "has_audio_asset": True, "has_whisper": True}
```

- [ ] **Step 2: Run, verify FAIL.**

- [ ] **Step 3: Implement in `scripts/hsvcc.py`**

```python
import json
from dataclasses import asdict, field
from pathlib import Path


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
```

- [ ] **Step 4: Run all tests, verify PASS.**

- [ ] **Step 5: Commit** — `git commit -m "feat: add meeting manifest model with status recomputation"`

---

### Task 5: `discover` command

**Files:**
- Create: `tests/test_discover.py`
- Modify: `scripts/hsvcc.py`

**Interfaces:**
- Consumes: everything from Tasks 1–4.
- Produces: `iter_archive_video_urls(session, since: date) -> list[str]` (paginates, stops when a page yields only pre-`since` dates); `discover(since: date, meetings_dir: Path, session: requests.Session) -> int` (returns count of failures); `download_file(url: str, dest: Path, session: requests.Session) -> None`; CLI `main(argv)` with `discover [--since YYYY-MM-DD]`.

- [ ] **Step 1: Write failing tests** (`tests/test_discover.py`) — fake session serving canned archive/video/API responses for one meeting; assert meeting dir created with `meeting.json`, `captions.vtt`, `captions.txt`, `agenda.pdf`; assert idempotency (second run downloads nothing new — fake session records call count); assert per-meeting failure (video page 500) is counted but doesn't raise.

```python
from datetime import date
from pathlib import Path
from typing import Any

import hsvcc
from hsvcc import Manifest, discover

ARCHIVE_HTML = '<a href="https://www.huntsvilleal.gov/videos/huntsville-city-council-meeting-june-25-2026-2/">x</a>'
VIDEO_HTML = ('<h1 class="full-width-headline">Huntsville City Council Meeting &#8211; June 25, 2026</h1>'
              '<iframe src="https://cloud.castus.tv/vod/hsv-tv/embed/6a3dcff79537260002c64cd9"></iframe>')
LEGISTAR_EVENTS = [{
    "EventId": 1223, "EventDate": "2026-06-25T00:00:00",
    "EventBodyName": "City Council Regular Meeting",
    "EventAgendaFile": "https://legistar/agenda.pdf", "EventMinutesFile": None,
    "EventInSiteURL": "https://huntsvilleal.legistar.com/MeetingDetail.aspx?LEGID=1223",
}]


class FakeResponse:
    def __init__(self, *, text: str = "", payload: Any = None, content: bytes = b"",
                 status: int = 200) -> None:
        self.text, self._payload, self.content, self.status_code = text, payload, content, status

    def json(self) -> Any:
        return self._payload

    def iter_content(self, chunk_size: int) -> Any:
        yield self.content

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *a: Any) -> None:
        pass


class FakeSession:
    """Routes by URL substring; records GET/POST urls."""

    def __init__(self, video_status: int = 200) -> None:
        self.calls: list[str] = []
        self.video_status = video_status

    def get(self, url: str, params: Any = None, timeout: int = 0, stream: bool = False) -> FakeResponse:
        self.calls.append(url)
        if "videocategory" in url and "page/2" in url:
            return FakeResponse(status=404)
        if "videocategory" in url:
            return FakeResponse(text=ARCHIVE_HTML)
        if "/videos/" in url:
            return FakeResponse(text=VIDEO_HTML, status=self.video_status)
        if "webapi.legistar.com" in url:
            return FakeResponse(payload=LEGISTAR_EVENTS)
        if url.endswith(".pdf"):
            return FakeResponse(content=b"%PDF-fake")
        if ".vtt" in url:
            return FakeResponse(text="WEBVTT\n\n00:01:00.000 --> 00:01:01.000\nHello.\n")
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url: str, json: Any = None, timeout: int = 0) -> FakeResponse:
        self.calls.append(url)
        if url.endswith("/upload/get"):
            return FakeResponse(payload={"response": {"payload": {"data": "https://cdn/out_1080.mp4?sig"}}})
        if url.endswith("/upload/get-captions"):
            return FakeResponse(payload={"response": {"payload": "https://s3/cap.vtt?sig"}})
        raise AssertionError(f"unexpected POST {url}")


def test_discover_creates_meeting_folder(tmp_path: Path) -> None:
    failures = discover(date(2026, 4, 1), tmp_path, FakeSession())  # type: ignore[arg-type]
    assert failures == 0
    mdir = tmp_path / "2026-06-25-city-council-meeting"
    m = Manifest.load(mdir)
    assert m.castus_id == "6a3dcff79537260002c64cd9"
    assert m.mp4_url == "https://cdn/out_1080.mp4"
    assert m.legistar_event_id == 1223
    assert (mdir / "captions.vtt").exists()
    assert "[00:01:00]" in (mdir / "captions.txt").read_text()
    assert (mdir / "agenda.pdf").read_bytes() == b"%PDF-fake"
    assert m.status["has_agenda"] and m.status["has_captions"]


def test_discover_idempotent(tmp_path: Path) -> None:
    discover(date(2026, 4, 1), tmp_path, FakeSession())  # type: ignore[arg-type]
    s2 = FakeSession()
    discover(date(2026, 4, 1), tmp_path, s2)  # type: ignore[arg-type]
    assert not any(u.endswith(".pdf") or ".vtt" in u for u in s2.calls)


def test_discover_counts_failures(tmp_path: Path) -> None:
    failures = discover(date(2026, 4, 1), tmp_path, FakeSession(video_status=500))  # type: ignore[arg-type]
    assert failures == 1
    assert not (tmp_path / "2026-06-25-city-council-meeting").exists()
```

- [ ] **Step 2: Run, verify FAIL.**

- [ ] **Step 3: Implement in `scripts/hsvcc.py`** — pagination, per-meeting build, downloads, wiring:

```python
import argparse
import sys

ARCHIVE_URL = "https://www.huntsvilleal.gov/videocategory/city-council-meetings/"
REPO_ROOT = Path(__file__).resolve().parent.parent
MEETINGS_DIR = REPO_ROOT / "meetings"
AUDIO_DIR = REPO_ROOT / "audio"


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
        in_range = [u for u in links if (d := date_from_slug(u)) is None or d >= since]
        urls.extend(u for u in in_range if u not in urls)
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
    # refresh late-published minutes URL from Legistar
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
```

And the CLI entry:

```python
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
```

- [ ] **Step 4: Run all tests, verify PASS.**

- [ ] **Step 5: Commit** — `git commit -m "feat: add discover command with pagination and idempotent downloads"`

---

### Task 6: `fetch-audio` command

**Files:**
- Create: `tests/test_fetch_audio.py`
- Modify: `scripts/hsvcc.py`

**Interfaces:**
- Produces: `fetch_audio(slugs: list[str], all_pending: bool, publish: bool, meetings_dir: Path, audio_dir: Path, session: requests.Session, run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> int`. Behavior: for each target meeting, if `audio/<slug>.opus` exists → skip. Else try `gh release download <tag> --pattern '*.opus' --dir audio/` (skip this attempt when `publish=True`); on failure download `mp4_url` to `audio/<slug>.mp4`, run `ffmpeg -y -i <mp4> -vn -ac 1 -ar 16000 -c:a libopus -b:a 24k <opus>`, delete the MP4. With `publish=True` additionally `gh release create <tag> <opus> --title <tag> --notes <mp4_url>` (fall back to `gh release upload` if the release exists), set `status.has_audio_asset=True`, save manifest. CLI: `fetch-audio [slugs...] [--all-pending] [--publish]`.

- [ ] **Step 1: Write failing tests** — fake `run` records commands; simulate `gh` failure → assert ffmpeg fallback + MP4 deleted; simulate `publish=True` → assert `gh release create` called and manifest flag set. Use `FakeSession` from test_discover (move shared fakes into `tests/fakes.py` and import from both test files).

```python
from pathlib import Path
from typing import Any

from fakes import FakeResponse, FakeSession  # tests/fakes.py — shared with test_discover
from hsvcc import Manifest, fetch_audio


class FakeRun:
    def __init__(self, fail_prefixes: tuple[str, ...] = ()) -> None:
        self.commands: list[list[str]] = []
        self.fail_prefixes = fail_prefixes

    def __call__(self, cmd: list[str], **kwargs: Any) -> Any:
        self.commands.append(cmd)
        rc = 1 if any(" ".join(cmd).startswith(p) for p in self.fail_prefixes) else 0
        if rc == 0 and cmd[0] == "ffmpeg":
            Path(cmd[-1]).write_bytes(b"opus")
        class R:
            returncode = rc
        return R()


def make_meeting(meetings_dir: Path) -> Manifest:
    m = Manifest(slug="2026-06-25-city-council-meeting", title="t", date="2026-06-25",
                 body=None, video_page_url="u", castus_id="abc",
                 mp4_url="https://cdn/out_1080.mp4", legistar_event_id=None,
                 legistar_url=None, agenda_url=None, minutes_url=None,
                 audio_asset_tag="audio-2026-06-25-city-council-meeting")
    m.save(meetings_dir / m.slug)
    return m


def test_fetch_audio_prefers_release_asset(tmp_path: Path) -> None:
    meetings, audio = tmp_path / "m", tmp_path / "a"
    m = make_meeting(meetings)
    run = FakeRun()
    # gh succeeds; fake it producing the file
    def gh_run(cmd: list[str], **kw: Any) -> Any:
        (audio / f"{m.slug}.opus").parent.mkdir(parents=True, exist_ok=True)
        (audio / f"{m.slug}.opus").write_bytes(b"opus")
        return run(cmd, **kw)
    rc = fetch_audio([m.slug], False, False, meetings, audio, FakeSession(), run=gh_run)  # type: ignore[arg-type]
    assert rc == 0
    assert run.commands[0][:3] == ["gh", "release", "download"]
    assert not any(c[0] == "ffmpeg" for c in run.commands)


def test_fetch_audio_falls_back_to_mp4(tmp_path: Path) -> None:
    meetings, audio = tmp_path / "m", tmp_path / "a"
    m = make_meeting(meetings)
    run = FakeRun(fail_prefixes=("gh release download",))
    rc = fetch_audio([m.slug], False, False, meetings, audio, FakeSession(), run=run)  # type: ignore[arg-type]
    assert rc == 0
    assert any(c[0] == "ffmpeg" for c in run.commands)
    assert not (audio / f"{m.slug}.mp4").exists()
    assert (audio / f"{m.slug}.opus").exists()


def test_fetch_audio_publish_uploads_release(tmp_path: Path) -> None:
    meetings, audio = tmp_path / "m", tmp_path / "a"
    m = make_meeting(meetings)
    run = FakeRun()
    rc = fetch_audio([m.slug], False, True, meetings, audio, FakeSession(), run=run)  # type: ignore[arg-type]
    assert rc == 0
    assert any(c[:3] == ["gh", "release", "create"] for c in run.commands)
    assert Manifest.load(meetings / m.slug).status["has_audio_asset"] is True
```

Note: `FakeSession.get` must serve `https://cdn/out_1080.mp4` with `stream=True` (add an `.mp4` route returning `FakeResponse(content=b"video")`).

- [ ] **Step 2: Run, verify FAIL.**

- [ ] **Step 3: Implement**

```python
import subprocess
from typing import Callable

RunFn = Callable[..., Any]


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
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL: {slug}: {exc}", file=sys.stderr)
    return 1 if failures else 0
```

CLI wiring in `main`:

```python
    p_audio = sub.add_parser("fetch-audio", help="get audio (release asset or MP4+ffmpeg)")
    p_audio.add_argument("slugs", nargs="*")
    p_audio.add_argument("--all-pending", action="store_true")
    p_audio.add_argument("--publish", action="store_true",
                         help="extract from MP4 and upload as GitHub release asset (CI)")
    ...
    if args.command == "fetch-audio":
        return fetch_audio(args.slugs, args.all_pending, args.publish,
                           MEETINGS_DIR, AUDIO_DIR, session)
```

- [ ] **Step 4: Run all tests, verify PASS.**

- [ ] **Step 5: Commit** — `git commit -m "feat: add fetch-audio with release-asset preference and publish mode"`

---

### Task 7: `transcribe` command

**Files:**
- Create: `tests/test_transcribe.py`
- Modify: `scripts/hsvcc.py`

**Interfaces:**
- Produces: `transcribe(slugs: list[str], all_pending: bool, meetings_dir: Path, audio_dir: Path, model_name: str = "medium") -> int` — lazy-imports `whisper`, loads model once, serial loop; writes `transcript/whisper-<model>.txt` (plain text) and `.srt` (from segments); updates manifest. `segments_to_srt(segments: list[dict]) -> str` is a pure helper.

- [ ] **Step 1: Write failing tests** — `segments_to_srt` pure test + `transcribe` with a fake `whisper` module injected via `sys.modules`:

```python
import sys
import types
from pathlib import Path
from typing import Any

from hsvcc import Manifest, segments_to_srt, transcribe
from test_fetch_audio import make_meeting


def test_segments_to_srt() -> None:
    srt = segments_to_srt([{"start": 0.0, "end": 1.5, "text": " Hello."},
                           {"start": 61.0, "end": 62.0, "text": " World."}])
    assert srt.startswith("1\n00:00:00,000 --> 00:00:01,500\nHello.\n")
    assert "2\n00:01:01,000 --> 00:01:02,000\nWorld.\n" in srt


def test_transcribe_writes_outputs(tmp_path: Path) -> None:
    meetings, audio = tmp_path / "m", tmp_path / "a"
    m = make_meeting(meetings)
    audio.mkdir(parents=True)
    (audio / f"{m.slug}.opus").write_bytes(b"opus")

    fake = types.ModuleType("whisper")
    def load_model(name: str, device: str = "cpu") -> Any:
        class Model:
            def transcribe(self, path: str, **kw: Any) -> dict:
                return {"text": "Full transcript.",
                        "segments": [{"start": 0.0, "end": 1.0, "text": " Full transcript."}]}
        return Model()
    fake.load_model = load_model  # type: ignore[attr-defined]
    sys.modules["whisper"] = fake
    try:
        rc = transcribe([m.slug], False, meetings, audio)
    finally:
        del sys.modules["whisper"]
    assert rc == 0
    tdir = meetings / m.slug / "transcript"
    assert (tdir / "whisper-medium.txt").read_text() == "Full transcript.\n"
    assert (tdir / "whisper-medium.srt").exists()
    assert Manifest.load(meetings / m.slug).status["has_whisper"] is True
```

- [ ] **Step 2: Run, verify FAIL.**

- [ ] **Step 3: Implement**

```python
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
    device = "mps" if sys.platform == "darwin" else "cpu"
    model = whisper.load_model(model_name, device=device)
    failures = 0
    for slug in slugs:  # serial — MPS does not parallelize
        try:
            audio_path = audio_dir / f"{slug}.opus"
            if not audio_path.exists():
                raise FileNotFoundError(f"{audio_path} missing — run fetch-audio first")
            print(f"transcribing {slug} (this takes a while)...")
            result = model.transcribe(str(audio_path), language="en", fp16=False)
            tdir = meetings_dir / slug / "transcript"
            tdir.mkdir(parents=True, exist_ok=True)
            (tdir / f"whisper-{model_name}.txt").write_text(result["text"].strip() + "\n")
            (tdir / f"whisper-{model_name}.srt").write_text(segments_to_srt(result["segments"]))
            manifest = Manifest.load(meetings_dir / slug)
            recompute_status(meetings_dir / slug, manifest)
            manifest.save(meetings_dir / slug)
            print(f"ok: transcribed {slug}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL: {slug}: {exc}", file=sys.stderr)
    return 1 if failures else 0
```

CLI wiring: `transcribe [slugs...] [--all-pending] [--model medium]`.

Note: `recompute_status` keys off `whisper-medium.txt` specifically; with a non-default `--model` the flag stays false — acceptable, medium is the canonical model.

- [ ] **Step 4: Run all tests, verify PASS.**

- [ ] **Step 5: Commit** — `git commit -m "feat: add transcribe command with lazy whisper import"`

---

### Task 8: GitHub Action + README

**Files:**
- Create: `.github/workflows/sync.yml`, `README.md`

- [ ] **Step 1: Write `.github/workflows/sync.yml`**

```yaml
name: Sync meetings
on:
  schedule:
    - cron: "0 13 * * 5"   # Fridays 13:00 UTC — meetings are Thursday evenings
  workflow_dispatch:

concurrency:
  group: sync
  cancel-in-progress: false

permissions:
  contents: write

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      - run: sudo apt-get update && sudo apt-get install -y ffmpeg
      - name: Discover meetings (agendas, captions, manifests)
        run: python3 scripts/hsvcc.py discover
      - name: Commit discovered artifacts
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add meetings/
          git diff --cached --quiet || git commit -m "chore: sync meetings $(date -u +%F)"
      - name: Extract + publish audio release assets
        env:
          GH_TOKEN: ${{ github.token }}
        run: python3 scripts/hsvcc.py fetch-audio --all-pending --publish
      - name: Commit manifest audio flags
        run: |
          git add meetings/
          git diff --cached --quiet || git commit -m "chore: record published audio assets"
          git push
```

- [ ] **Step 2: Write `README.md`** — what the repo is, folder layout, the three CLI commands with examples, local whisper setup (`pip install -r requirements-dev.txt openai-whisper`), how the Action works, and a "for LLM note-taking" section pointing at `captions.txt` / `transcript/whisper-medium.txt` + `agenda.pdf` per meeting folder.

- [ ] **Step 3: Validate workflow syntax** — `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/sync.yml'))"` (PyYAML available via system) or visual review if PyYAML missing.

- [ ] **Step 4: Commit** — `git commit -m "ci: add weekly sync workflow and README"`

---

### Task 9: Live backfill (April 2026 →)

**Files:** produces `meetings/*` content only.

- [ ] **Step 1:** `python3 scripts/hsvcc.py discover --since 2026-04-01` (live network). Review output: expect ~6–8 meetings (Apr 9, Apr 23, May 14, May 28, Jun 1 joint session, Jun 11, Jun 25; possibly others).
- [ ] **Step 2:** Spot-check one folder: manifest fields populated, `agenda.pdf` opens, `captions.txt` readable.
- [ ] **Step 3:** Run full test suite one more time: `python3 -m pytest -v`.
- [ ] **Step 4:** Commit: `git add meetings/ && git commit -m "feat: backfill meetings since April 2026"`.
- [ ] **Step 5:** Create the private GitHub repo and push (ASK USER unless already authorized): `gh repo create Caden-Helbling/hsv-city-council-transcripts --private --source . --push`.
- [ ] **Step 6:** Local audio + whisper runs are long (hours) — kick off `fetch-audio --all-pending` in the background and report; `transcribe --all-pending` can run overnight.

## Self-review notes

- Spec coverage: VTT render (T1), enumeration/parsers (T2), Castus/Legistar (T3), manifest (T4), discover (T5), fetch-audio + release assets (T6), whisper (T7), Action + docs (T8), backfill (T9). `ci-audio` from spec realized as `fetch-audio --publish` (single code path, less duplication).
- Types/signatures consistent across tasks (checked `Manifest` fields, `fetch_audio`/`transcribe` signatures, `_pending_slugs` shared helper).
- No placeholders; all code blocks complete.
