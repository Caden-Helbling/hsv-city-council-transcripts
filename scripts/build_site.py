#!/usr/bin/env python3
"""Build the static site (GitHub Pages) from meetings/ data.

Phase 1 of docs/superpowers/plans/2026-08-13-github-pages-site.md: a history
site — an index of all archived meetings plus one page per meeting rendering
the manifest, votes, notes, and pre-meeting agenda preview that the pipeline
already produces. Deterministic: data in the repo -> HTML in _site/, no
network calls, no LLM.
"""
from __future__ import annotations

import html
import json
import shutil
import re
import sys
from datetime import date
from pathlib import Path

import markdown

REPO = "Caden-Helbling/hsv-city-council-transcripts"
BLOB_URL = f"https://github.com/{REPO}/blob/main"
RELEASE_URL = f"https://github.com/{REPO}/releases/tag"
REPO_ROOT = Path(__file__).resolve().parent.parent
MEETINGS_DIR = REPO_ROOT / "meetings"
SITE_DIR = REPO_ROOT / "_site"

MD_EXTENSIONS = ["tables", "fenced_code", "sane_lists"]

CSS = """
:root {
  --bg: #fdfdfc; --fg: #1c1e21; --muted: #5c6570; --line: #e3e5e8;
  --accent: #0b5cad; --card: #f4f5f3;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #15171a; --fg: #e8eaed; --muted: #9aa4af; --line: #2e3338;
    --accent: #82b6e6; --card: #1d2024;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--fg);
  font: 16px/1.6 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
main { max-width: 48rem; margin: 0 auto; padding: 0 1.25rem 4rem; }
.site-header {
  border-bottom: 1px solid var(--line); margin-bottom: 1.5rem;
}
.site-header > div {
  max-width: 48rem; margin: 0 auto; padding: 0.75rem 1.25rem;
}
.site-header a { color: var(--fg); text-decoration: none; font-weight: 600; }
.site-footer {
  border-top: 1px solid var(--line); margin-top: 3rem; color: var(--muted);
  font-size: 0.85rem;
}
.site-footer > div { max-width: 48rem; margin: 0 auto; padding: 1rem 1.25rem; }
a { color: var(--accent); }
h1 { line-height: 1.25; margin: 1.5rem 0 0.25rem; font-size: 1.6rem; }
h2 { margin-top: 2.25rem; font-size: 1.25rem; }
.meta { color: var(--muted); margin-top: 0; }
.crumb { font-size: 0.9rem; margin: 1.25rem 0 0; }
.crumb a { text-decoration: none; }
ul.meeting-list { list-style: none; padding: 0; }
ul.meeting-list li {
  padding: 0.65rem 0; border-bottom: 1px solid var(--line);
}
ul.meeting-list .date {
  display: inline-block; min-width: 6.5rem; color: var(--muted);
  font-variant-numeric: tabular-nums;
}
.badge {
  display: inline-block; font-size: 0.72rem; padding: 0.05em 0.55em;
  margin-left: 0.35em; border: 1px solid var(--line); border-radius: 999px;
  color: var(--muted); white-space: nowrap;
}
ul.links { padding-left: 1.25rem; }
ul.links li { margin: 0.15rem 0; }
table { border-collapse: collapse; font-size: 0.92rem; }
th, td {
  text-align: left; padding: 0.35rem 0.7rem; border-bottom: 1px solid var(--line);
  vertical-align: top;
}
th { color: var(--muted); font-weight: 600; }
.md table { display: block; overflow-x: auto; }
.md h2 { border-bottom: 1px solid var(--line); padding-bottom: 0.2rem; }
.md blockquote {
  margin: 1rem 0; padding: 0.1rem 1rem; border-left: 3px solid var(--line);
  color: var(--muted); background: var(--card);
}
.md code {
  background: var(--card); padding: 0.1em 0.35em; border-radius: 4px;
  font-size: 0.9em;
}
.md pre { background: var(--card); padding: 0.75rem 1rem; overflow-x: auto; }
.md pre code { background: none; padding: 0; }
details { margin: 1rem 0; }
details > summary { cursor: pointer; color: var(--accent); }
.note { color: var(--muted); font-size: 0.9rem; }
"""


def _fmt_date(iso: str, *, long: bool = False) -> str:
    d = date.fromisoformat(iso)
    if long:
        return f"{d.strftime('%A, %B')} {d.day}, {d.year}"
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def _md(text: str) -> str:
    return markdown.markdown(text, extensions=MD_EXTENSIONS)


def _demote_headings(md_text: str) -> str:
    """Push every heading down one level so embedded docs nest under the page h1."""
    return re.sub(r"^(#{1,5})(\s)", r"#\1\2", md_text, flags=re.M)


def page(title: str, body: str, *, root: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{CSS}</style>
</head>
<body>
<header class="site-header"><div><a href="{root}index.html">Huntsville City Council — Meeting Archive</a></div></header>
<main>
{body}
</main>
<footer class="site-footer"><div>Unofficial archive generated from public records
(<a href="https://huntsvilleal.legistar.com">Legistar</a> agendas/minutes, official
video captions, Whisper transcripts). Source data and pipeline:
<a href="https://github.com/{REPO}">{REPO}</a>.</div></footer>
</body>
</html>
"""


def load_meeting(mdir: Path) -> dict:
    meeting = json.loads((mdir / "meeting.json").read_text(encoding="utf-8"))
    for name, key in (("notes.md", "notes_md"), ("agenda-preview.md", "preview_md")):
        f = mdir / name
        meeting[key] = f.read_text(encoding="utf-8") if f.exists() else None
    votes_f = mdir / "votes.json"
    meeting["votes"] = json.loads(votes_f.read_text(encoding="utf-8")) if votes_f.exists() else None
    meeting["has_captions_txt"] = (mdir / "captions.txt").exists()
    meeting["has_whisper_txt"] = (mdir / "transcript" / "whisper-medium.txt").exists()
    return meeting


def _badges(meeting: dict) -> str:
    labels = [label for label, present in (
        ("notes", meeting.get("notes_md")),
        ("transcript", meeting.get("has_whisper_txt")),
        ("captions", meeting.get("has_captions_txt")),
        ("votes", meeting.get("votes")),
        ("minutes", meeting.get("status", {}).get("has_minutes")),
    ) if present]
    return "".join(f'<span class="badge">{label}</span>' for label in labels)


def render_index(meetings: list[dict]) -> str:
    items = []
    for m in sorted(meetings, key=lambda m: (m["date"], m["slug"]), reverse=True):
        items.append(
            f'<li><span class="date">{_fmt_date(m["date"])}</span> '
            f'<a href="meetings/{html.escape(m["slug"])}/index.html">'
            f'{html.escape(m["title"])}</a>{_badges(m)}</li>')
    body = f"""<h1>Meeting archive</h1>
<p>Every archived Huntsville (AL) City Council meeting: what was on the agenda,
what was decided, and what was said — from the official Legistar records,
meeting video captions, and locally-run Whisper transcripts.</p>
<ul class="meeting-list">
{chr(10).join(items)}
</ul>"""
    return page("Huntsville City Council Meeting Archive", body, root="")


def _record_links(meeting: dict) -> str:
    slug = meeting["slug"]
    links: list[tuple[str, str, str]] = []  # (label, url, note)
    if meeting.get("agenda_url"):
        links.append(("Agenda (PDF)", meeting["agenda_url"], "official"))
    if meeting.get("minutes_url"):
        links.append(("Minutes (PDF)", meeting["minutes_url"], "official"))
    if meeting.get("legistar_url"):
        links.append(("Legistar meeting detail", meeting["legistar_url"], "official"))
    if meeting.get("video_page_url"):
        links.append(("Meeting video", meeting["video_page_url"], "huntsvilleal.gov"))
    if meeting.get("has_whisper_txt"):
        links.append(("Whisper transcript",
                      f"{BLOB_URL}/meetings/{slug}/transcript/whisper-medium.txt", "text"))
    if meeting.get("has_captions_txt"):
        links.append(("Official captions",
                      f"{BLOB_URL}/meetings/{slug}/captions.txt", "text"))
    if meeting.get("status", {}).get("has_audio_asset"):
        links.append(("Audio (opus)",
                      f"{RELEASE_URL}/{meeting['audio_asset_tag']}", "release asset"))
    lis = [f'<li><a href="{html.escape(url)}">{html.escape(label)}</a> '
           f'<span class="note">({note})</span></li>' for label, url, note in links]
    return "<ul class=\"links\">\n" + "\n".join(lis) + "\n</ul>"


def _votes_table(votes: dict) -> str:
    rows = []
    for item in votes.get("items", []):
        vote = item.get("vote")
        if vote is None:
            kind, aye, nay = "—", "", ""
        else:
            kind = "Consent agenda" if vote["consent"] else "Individual roll-call"
            aye, nay = ", ".join(vote["aye"]), ", ".join(vote["nay"]) or "None"
        rows.append(f"<tr><td>{html.escape(item['number'])}</td>"
                    f"<td>{kind}</td><td>{html.escape(aye)}</td>"
                    f"<td>{html.escape(nay)}</td></tr>")
    return ("<table><thead><tr><th>No.</th><th>Vote</th><th>Aye</th><th>Nay</th>"
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
            '<p class="note">Items with — were recorded without a roll-call '
            "(voice vote, or merely presented/introduced).</p>")


def render_meeting_page(meeting: dict) -> str:
    parts = ['<p class="crumb"><a href="../../index.html">← All meetings</a></p>',
             f"<h1>{html.escape(meeting['title'])}</h1>"]
    meta = _fmt_date(meeting["date"], long=True)
    if meeting.get("body"):
        meta += f" · {html.escape(meeting['body'])}"
    parts.append(f'<p class="meta">{meta}</p>')
    parts.append("<h2>Records</h2>")
    parts.append(_record_links(meeting))
    if meeting.get("votes"):
        parts.append("<h2>Votes</h2>")
        parts.append(_votes_table(meeting["votes"]))
    if meeting.get("notes_md"):
        parts.append("<h2>Notes</h2>")
        parts.append('<p class="note">Written from the transcript and agenda; '
                     "unofficial.</p>")
        parts.append(f'<div class="md">{_md(_demote_headings(meeting["notes_md"]))}</div>')
    if meeting.get("preview_md"):
        parts.append("<details><summary>Pre-meeting agenda preview</summary>")
        parts.append(f'<div class="md">{_md(_demote_headings(meeting["preview_md"]))}</div>')
        parts.append("</details>")
    return page(meeting["title"], "\n".join(parts), root="../../")


def build(meetings_dir: Path, site_dir: Path) -> int:
    if site_dir.exists():
        shutil.rmtree(site_dir)
    site_dir.mkdir(parents=True)
    (site_dir / ".nojekyll").write_text("")
    meetings = [load_meeting(d) for d in sorted(meetings_dir.iterdir())
                if (d / "meeting.json").exists()]
    (site_dir / "index.html").write_text(render_index(meetings), encoding="utf-8")
    for meeting in meetings:
        out = site_dir / "meetings" / meeting["slug"]
        out.mkdir(parents=True)
        (out / "index.html").write_text(render_meeting_page(meeting), encoding="utf-8")
    print(f"built {len(meetings)} meeting pages -> {site_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(build(MEETINGS_DIR, SITE_DIR))
