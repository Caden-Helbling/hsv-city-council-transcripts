import json
from datetime import date
from pathlib import Path

import pytest

from fakes import FakeResponse, FakeSession
from hsvcc import (Manifest, backfill_previews, check_links,
                   fetch_agenda_attachments, parse_agenda_items,
                   preview_agendas, prune_upcoming, render_agenda_preview)

AGENDA_TEXT = """
Tommy Battle, Mayor
CITY COUNCIL CHAMBERS 5:30 PM Thursday, July 23, 2026
REGULAR MEETING OF THE CITY COUNCIL
CALL TO ORDER
1. INVOCATION
Offered by: Huntsville Alabama Public Safety Chaplains
6. COUNCIL: SPECIAL RECOGNITIONS AND RESOLUTIONS
Special Recognitions
a. Resolution honoring the 10th Cavalry Hill Buffalo Soldiers American
Legion Post 351 for over 60 years of Service.
Resolution No. 26-616
2026-739
Sponsors: Watkins
Buffalo Soldiers 072326.pdfAttachments:
7. ANNOUNCEMENTS AND PRESENTATIONS
a. Update on Northern Bypass Project.2026-742
Sponsors: Watkins
Page 3 of 13
City Council Regular Meeting Agenda July 23, 2026
20. NEW BUSINESS ITEMS FOR CONSIDERATION OR ACTION
These items will be approved in one motion unless any member of the Council wishes to remove an
item for discussion.
a. Resolution authorizing travel expenses.
Resolution No. 26-629
2026-761
Sponsors: Finance
23. ADJOURNMENT
"""


def test_parse_agenda_sections_and_items() -> None:
    sections = parse_agenda_items(AGENDA_TEXT)
    assert [s["number"] for s in sections] == [1, 6, 7, 20, 23]
    recog = sections[1]
    assert recog["heading"] == "COUNCIL: SPECIAL RECOGNITIONS AND RESOLUTIONS"
    assert len(recog["items"]) == 1
    item = recog["items"][0]
    # multi-line title joined; boilerplate/attachments not swallowed
    assert item["title"].startswith("Resolution honoring the 10th Cavalry")
    assert item["title"].endswith("60 years of Service.")
    assert item["matter_number"] == "Resolution No. 26-616"
    assert item["file_id"] == "2026-739"
    assert item["sponsors"] == "Watkins"


def test_parse_agenda_splits_glued_file_id() -> None:
    item = parse_agenda_items(AGENDA_TEXT)[2]["items"][0]
    assert item["title"] == "Update on Northern Bypass Project."
    assert item["file_id"] == "2026-742"


def test_parse_agenda_ignores_page_noise_and_section_boilerplate() -> None:
    new_business = parse_agenda_items(AGENDA_TEXT)[3]
    assert len(new_business["items"]) == 1
    assert new_business["items"][0]["title"] == "Resolution authorizing travel expenses."


def test_render_preview_lists_topics_and_broken_links() -> None:
    event = {"EventDate": "2026-07-23T00:00:00", "EventBodyName": "City Council Regular Meeting",
             "EventTime": "5:30 PM", "EventLocation": "Council Chambers",
             "EventInSiteURL": "https://legistar/detail", "EventAgendaFile": "https://legistar/a.pdf"}
    links = [{"url": "https://ok", "status": 200, "ok": True},
             {"url": "https://gone", "status": 404, "ok": False}]
    md = render_agenda_preview(event, parse_agenda_items(AGENDA_TEXT), links, "2026-08-13")
    assert md.startswith("# Agenda preview — City Council Regular Meeting, 2026-07-23")
    assert "### 6. COUNCIL: SPECIAL RECOGNITIONS AND RESOLUTIONS" in md
    assert "*(Resolution No. 26-616, file 2026-739, sponsors: Watkins)*" in md
    assert "1. INVOCATION" in md  # itemless sections still listed
    assert "1/2 agenda links OK." in md
    assert "- HTTP 404 — https://gone" in md


def test_check_links_records_status() -> None:
    session = FakeSession()
    results = check_links(["https://x/file.pdf"], session)
    assert results == [{"url": "https://x/file.pdf", "status": 200, "ok": True}]


def _make_upcoming(upcoming: Path, name: str, event_id: int) -> Path:
    pdir = upcoming / name
    pdir.mkdir(parents=True)
    (pdir / "event.json").write_text(json.dumps({"EventId": event_id}))
    (pdir / "agenda-preview.md").write_text("# preview\n")
    return pdir


def _make_meeting(meetings: Path, slug: str, event_id: int) -> Path:
    mdir = meetings / slug
    manifest = Manifest(slug=slug, title="t", date=slug[:10], body=None,
                        video_page_url="v", castus_id="c", mp4_url="m",
                        legistar_event_id=event_id, legistar_url=None,
                        agenda_url=None, minutes_url=None, audio_asset_tag=f"audio-{slug}")
    manifest.save(mdir)
    return mdir


def test_prune_archives_preview_into_matching_meeting(tmp_path: Path) -> None:
    upcoming, meetings = tmp_path / "upcoming", tmp_path / "meetings"
    pdir = _make_upcoming(upcoming, "2026-06-25-city-council-regular-meeting", 1223)
    mdir = _make_meeting(meetings, "2026-06-25-city-council-meeting", 1223)
    prune_upcoming(upcoming, meetings, today=date(2026, 6, 27))
    assert not pdir.exists()
    assert (mdir / "agenda-preview.md").read_text() == "# preview\n"


def test_prune_keeps_future_and_recent_unmatched_previews(tmp_path: Path) -> None:
    upcoming, meetings = tmp_path / "upcoming", tmp_path / "meetings"
    meetings.mkdir()
    future = _make_upcoming(upcoming, "2026-07-09-city-council-regular-meeting", 1)
    recent_unmatched = _make_upcoming(upcoming, "2026-06-25-city-council-regular-meeting", 2)
    stale = _make_upcoming(upcoming, "2026-05-01-city-council-regular-meeting", 3)
    prune_upcoming(upcoming, meetings, today=date(2026, 7, 1))
    assert future.exists()  # meeting hasn't happened
    assert recent_unmatched.exists()  # grace period: discover may not have run yet
    assert not stale.exists()  # >14 days past, give up


def test_preview_agendas_writes_folder_from_legistar_event(tmp_path: Path) -> None:
    upcoming, meetings = tmp_path / "upcoming", tmp_path / "meetings"
    meetings.mkdir()
    session = FakeSession()
    rc = preview_agendas(7, upcoming, meetings, session, today=date(2026, 6, 20))
    assert rc == 0
    pdir = upcoming / "2026-06-25-city-council-regular-meeting"
    assert (pdir / "agenda.pdf").read_bytes() == b"%PDF-fake"
    assert json.loads((pdir / "event.json").read_text())["EventId"] == 1223
    md = (pdir / "agenda-preview.md").read_text(encoding="utf-8")
    assert md.startswith("# Agenda preview — City Council Regular Meeting, 2026-06-25")
    # fake PDF bytes: no text or links extractable, rendered as such
    assert "no items parsed" in md
    assert "no links found" in md


def test_backfill_previews_builds_from_archived_pdf(tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    import hsvcc

    meetings = tmp_path / "meetings"
    mdir = _make_meeting(meetings, "2026-06-25-city-council-meeting", 1223)
    (mdir / "agenda.pdf").write_bytes(b"%PDF-fake")
    done = _make_meeting(meetings, "2026-05-14-city-council-meeting", 9)
    (done / "agenda.pdf").write_bytes(b"%PDF-fake")
    (done / "agenda-preview.md").write_text("existing", encoding="utf-8")
    no_pdf = _make_meeting(meetings, "2026-04-09-city-council-meeting", 8)

    monkeypatch.setattr(hsvcc, "_pdf_text", lambda p: AGENDA_TEXT)
    monkeypatch.setattr(hsvcc, "extract_pdf_links", lambda p: ["https://x/file.pdf"])
    rc = backfill_previews(meetings, FakeSession(), today=date(2026, 8, 18))
    assert rc == 0
    md = (mdir / "agenda-preview.md").read_text(encoding="utf-8")
    assert md.startswith("# Agenda preview —")
    assert "Resolution No. 26-616" in md
    assert "1/1 agenda links OK." in md
    assert (done / "agenda-preview.md").read_text(encoding="utf-8") == "existing"
    assert not (no_pdf / "agenda-preview.md").exists()


class AttachmentFakeSession(FakeSession):
    """Extends the shared fake with Legistar matter-attachment routes."""

    def get(self, url, params=None, timeout=0, stream=False):  # type: ignore[override]
        self.calls.append(url)
        if "/matters/8434/attachments" in url:
            return FakeResponse(payload=[
                {"MatterAttachmentName": "Expenditures - Complete",
                 "MatterAttachmentHyperlink": "https://legistar/expenditures.pdf"},
                {"MatterAttachmentName": "Backup memo",
                 "MatterAttachmentHyperlink": "https://legistar/memo.pdf"},
            ])
        if url.endswith(".pdf"):
            return FakeResponse(content=b"%PDF-fake")
        return super().get(url, params=params, timeout=timeout, stream=stream)


def test_fetch_agenda_attachments_writes_matching_excerpts(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import hsvcc

    pdf = tmp_path / "agenda.pdf"
    pdf.write_bytes(b"%PDF-fake")
    dest = tmp_path / "agenda-attachments.md"
    monkeypatch.setattr(hsvcc, "extract_pdf_links", lambda p: [
        "https://huntsvilleal.legistar.com/gateway.aspx?m=l&id=/matter.aspx?key=8434",
        "https://huntsvilleal.legistar.com/gateway.aspx?M=F&ID=abc.pdf",
    ])
    monkeypatch.setattr(hsvcc, "_pdf_text", lambda p: "Grand Total $30,015,087.43")
    session = AttachmentFakeSession()
    assert fetch_agenda_attachments(pdf, dest, session) == 1
    text = dest.read_text(encoding="utf-8")
    assert "## Expenditures - Complete" in text
    assert "$30,015,087.43" in text
    assert "Backup memo" not in text  # name doesn't match the high-value patterns


def test_fetch_agenda_attachments_no_match_writes_nothing(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import hsvcc

    pdf = tmp_path / "agenda.pdf"
    pdf.write_bytes(b"%PDF-fake")
    dest = tmp_path / "agenda-attachments.md"
    monkeypatch.setattr(hsvcc, "extract_pdf_links", lambda p: [])
    assert fetch_agenda_attachments(pdf, dest, FakeSession()) == 0
    assert not dest.exists()


def test_backfill_previews_skips_unparseable_pdf(tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    import hsvcc

    meetings = tmp_path / "meetings"
    mdir = _make_meeting(meetings, "2026-06-25-city-council-meeting", 1223)
    (mdir / "agenda.pdf").write_bytes(b"%PDF-fake")
    monkeypatch.setattr(hsvcc, "_pdf_text", lambda p: None)
    assert backfill_previews(meetings, FakeSession(), today=date(2026, 8, 18)) == 0
    assert not (mdir / "agenda-preview.md").exists()


def test_preview_agendas_skips_meetings_outside_window(tmp_path: Path) -> None:
    upcoming, meetings = tmp_path / "upcoming", tmp_path / "meetings"
    meetings.mkdir()
    rc = preview_agendas(2, upcoming, meetings, FakeSession(), today=date(2026, 6, 20))
    assert rc == 0
    assert not upcoming.exists() or not list(upcoming.iterdir())
