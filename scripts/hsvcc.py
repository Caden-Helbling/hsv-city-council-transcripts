#!/usr/bin/env python3
"""HSV City Council transcript pipeline: discover / fetch-audio / transcribe."""
from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from datetime import date

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
