import json
from datetime import date
from pathlib import Path

from build_site import (_demote_headings, build, render_index, render_meeting_page)

TODAY = date(2026, 8, 18)


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


def _upcoming(**overrides) -> dict:
    base = {
        "slug": "2026-08-27-city-council-regular-meeting",
        "event": {"EventDate": "2026-08-27T00:00:00",
                  "EventBodyName": "City Council Regular Meeting",
                  "EventTime": "5:30 PM", "EventLocation": "Council Chambers",
                  "EventAgendaFile": "https://legistar/a.pdf",
                  "EventInSiteURL": "https://legistar/detail"},
        "preview_md": "# Agenda preview\n\n## Topics\n\n- Rezoning of 12 acres\n",
        "summary_md": None,
    }
    base.update(overrides)
    return base


def test_index_sorts_reverse_chronological_and_links_pages() -> None:
    older = _meeting(slug="2026-05-14-city-council-meeting", date="2026-05-14",
                     title="Older Meeting")
    html = render_index([older, _meeting()], [], TODAY)
    assert html.index("2026-06-25-city-council-meeting") < html.index("Older Meeting")
    assert 'href="meetings/2026-06-25-city-council-meeting/index.html"' in html
    assert '<span class="badge">transcript</span>' in html


def test_index_empty_state_when_no_upcoming_agendas() -> None:
    html = render_index([_meeting()], [], TODAY)
    assert "No upcoming meeting agendas posted yet" in html


def test_index_upcoming_card_falls_back_to_topic_list() -> None:
    html = render_index([], [_upcoming()], TODAY)
    assert "City Council Regular Meeting — Thursday, August 27, 2026" in html
    assert "Plain-language summary not generated yet" in html
    assert "<details><summary>Full agenda topics</summary>" in html
    assert "Rezoning of 12 acres" in html
    assert "https://legistar/a.pdf" in html


def test_index_upcoming_card_renders_summary_when_present() -> None:
    entry = _upcoming(summary_md="## In plain language\n\n- The city plans X\n")
    html = render_index([], [entry], TODAY)
    assert "The city plans X" in html
    assert "Plain-language summary not generated yet" not in html


def test_index_hides_upcoming_entries_for_past_meetings() -> None:
    stale = _upcoming(slug="2026-08-13-city-council-regular-meeting",
                      event={"EventDate": "2026-08-13T00:00:00",
                             "EventBodyName": "City Council Regular Meeting"})
    html = render_index([], [stale], TODAY)
    assert "August 13" not in html
    assert "No upcoming meeting agendas posted yet" in html


def test_meeting_page_renders_archived_summary() -> None:
    html = render_meeting_page(_meeting(summary_md="- Big rezoning vote\n"))
    assert "Big rezoning vote" in html
    assert "Written before the meeting" in html


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
