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
