import json
from pathlib import Path

from build_site import (_demote_headings, build, render_index, render_meeting_page)


def _meeting(**overrides) -> dict:
    base = {
        "slug": "2026-06-25-city-council-meeting",
        "title": "Huntsville City Council Meeting – June 25, 2026",
        "date": "2026-06-25", "body": "City Council Regular Meeting",
        "video_page_url": "https://www.huntsvilleal.gov/videos/x/",
        "castus_id": "c", "mp4_url": "m",
        "legistar_event_id": 1223, "legistar_url": "https://legistar/detail",
        "agenda_url": "https://legistar/agenda.pdf", "minutes_url": None,
        "audio_asset_tag": "audio-2026-06-25-city-council-meeting",
        "status": {"has_audio_asset": True, "has_minutes": False},
        "notes_md": None, "preview_md": None, "votes": None,
        "has_captions_txt": False, "has_whisper_txt": True,
    }
    base.update(overrides)
    return base


def test_index_sorts_reverse_chronological_and_links_pages() -> None:
    older = _meeting(slug="2026-05-14-city-council-meeting", date="2026-05-14",
                     title="Older Meeting")
    html = render_index([older, _meeting()])
    assert html.index("2026-06-25-city-council-meeting") < html.index("Older Meeting")
    assert 'href="meetings/2026-06-25-city-council-meeting/index.html"' in html
    assert '<span class="badge">transcript</span>' in html


def test_meeting_page_links_records() -> None:
    html = render_meeting_page(_meeting())
    assert "https://legistar/agenda.pdf" in html
    assert "releases/tag/audio-2026-06-25-city-council-meeting" in html
    assert "transcript/whisper-medium.txt" in html
    assert "Minutes" not in html  # unpublished minutes not linked


def test_meeting_page_renders_votes_table() -> None:
    votes = {"items": [
        {"number": "26-495", "vote": {"consent": False, "aye": ["Robinson", "Kling"],
                                      "nay": ["Little"]}},
        {"number": "26-616", "vote": {"consent": True, "aye": ["Robinson"], "nay": []}},
        {"number": "26-700", "vote": None},
    ]}
    html = render_meeting_page(_meeting(votes=votes))
    assert "<td>26-495</td><td>Individual roll-call</td><td>Robinson, Kling</td><td>Little</td>" in html
    assert "<td>26-616</td><td>Consent agenda</td><td>Robinson</td><td>None</td>" in html
    assert "<td>26-700</td><td>—</td>" in html


def test_meeting_page_renders_notes_with_demoted_headings() -> None:
    html = render_meeting_page(_meeting(notes_md="# Meeting Notes\n\n## TL;DR\n\n- point\n"))
    assert "<h2>Meeting Notes</h2>" in html
    assert "<h3>TL;DR</h3>" in html
    assert "<li>point</li>" in html


def test_meeting_page_puts_agenda_preview_in_details() -> None:
    html = render_meeting_page(_meeting(preview_md="# Agenda preview\n\n- item\n"))
    assert "<details><summary>Pre-meeting agenda preview</summary>" in html


def test_titles_are_escaped() -> None:
    html = render_meeting_page(_meeting(title="A <b>bold</b> & risky title"))
    assert "A &lt;b&gt;bold&lt;/b&gt; &amp; risky title" in html


def test_demote_headings_only_touches_heading_lines() -> None:
    assert _demote_headings("# a\ntext # not heading\n##### e\n") == \
        "## a\ntext # not heading\n###### e\n"


def test_build_writes_site_tree(tmp_path: Path) -> None:
    meetings = tmp_path / "meetings"
    mdir = meetings / "2026-06-25-city-council-meeting"
    mdir.mkdir(parents=True)
    manifest = {k: v for k, v in _meeting().items()
                if k not in ("notes_md", "preview_md", "votes",
                             "has_captions_txt", "has_whisper_txt")}
    (mdir / "meeting.json").write_text(json.dumps(manifest))
    (mdir / "notes.md").write_text("# Notes\n\nhello\n")
    site = tmp_path / "_site"
    assert build(meetings, site) == 0
    assert (site / ".nojekyll").exists()
    index = (site / "index.html").read_text(encoding="utf-8")
    assert "2026-06-25-city-council-meeting/index.html" in index
    page = (site / "meetings" / "2026-06-25-city-council-meeting" / "index.html")
    assert "hello" in page.read_text(encoding="utf-8")
