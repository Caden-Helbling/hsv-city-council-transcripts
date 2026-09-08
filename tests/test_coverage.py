"""Schedule-vs-archive coverage checks, and the calendar scrape behind them."""
from datetime import date
from pathlib import Path

from fakes import FakeResponse, FakeSession
from hsvcc import Manifest, coverage, parse_legistar_calendar

FIXTURE = Path(__file__).parent / "fixtures" / "legistar-calendar.html"

# One row per grid, shaped like Legistar's: the body name in a hypBody anchor,
# the date as a bare cell, the time in a lblTime span, and an agenda link that
# carries an href only when the agenda is actually published.
ROW = (
    '<tr class="rgRow" id="ctl00_ContentPlaceHolder1_{grid}_ctl00__{i}">'
    '<td><a id="x_{grid}_ctl00_ctl04_hypBody" href="DepartmentDetail.aspx?ID=1">'
    "{body}</a></td>"
    '<td class="rgSorted">{date}</td>'
    '<td><span id="x_{grid}_ctl00_ctl04_lblTime">{time}</span></td>'
    "<td>CITY COUNCIL CHAMBERS<br /><em></em></td>"
    '<td><a id="x_{grid}_ctl00_ctl04_hypAgenda"{agenda}>Agenda</a></td>'
    "</tr>"
)
AGENDA_HREF = ' href="View.ashx?M=A&amp;ID=1"'


def _page(*rows: str) -> str:
    return "<html><body><table>" + "".join(rows) + "</table></body></html>"


def _row(grid: str, i: int, body: str, day: str, time: str = "5:30 PM",
         agenda: bool = False) -> str:
    return ROW.format(grid=grid, i=i, body=body, date=day, time=time,
                      agenda=AGENDA_HREF if agenda else "")


def test_parse_calendar_reads_the_real_page() -> None:
    entries = parse_legistar_calendar(FIXTURE.read_text(encoding="utf-8"))
    # the fixture is the 2026-09-07 capture: five council meetings, and only
    # the one that already happened has an agenda posted
    assert [(e["date"], e["has_agenda"]) for e in entries] == [
        ("2026-09-01", True),
        ("2026-09-10", False),
        ("2026-09-18", False),
        ("2026-09-24", False),
        ("2026-09-29", False),
    ]
    assert entries[1]["body"] == "City Council Regular Meeting"
    assert entries[2]["time"] == "11:00 AM"


def test_parse_calendar_unions_both_grids() -> None:
    """gridUpcomingMeetings is capped and gridCalendar is month-scoped.

    On 2026-09-07 the upcoming grid listed 09-10/09-18/09-29 but omitted
    09-24, which only the month grid had - so either grid alone loses a
    meeting and the union is what makes the check trustworthy.
    """
    page = _page(
        _row("gridUpcomingMeetings", 0, "City Council Regular Meeting", "9/10/2026"),
        _row("gridCalendar", 0, "City Council Regular Meeting", "9/24/2026"),
    )
    assert [e["date"] for e in parse_legistar_calendar(page)] == [
        "2026-09-10", "2026-09-24"]


def test_parse_calendar_dedupes_preferring_the_row_with_an_agenda() -> None:
    page = _page(
        _row("gridUpcomingMeetings", 0, "City Council Regular Meeting", "9/10/2026"),
        _row("gridCalendar", 0, "City Council Regular Meeting", "9/10/2026",
             agenda=True),
    )
    entries = parse_legistar_calendar(page)
    assert len(entries) == 1 and entries[0]["has_agenda"]


def test_parse_calendar_skips_non_council_bodies() -> None:
    page = _page(_row("gridCalendar", 0, "Planning Commission", "9/15/2026"))
    assert parse_legistar_calendar(page) == []


class CalendarSession(FakeSession):
    """FakeSession plus a Legistar calendar page and a settable event list."""

    def __init__(self, calendar_rows: str, events: list[dict]) -> None:
        super().__init__()
        self.calendar_rows, self.events = calendar_rows, events

    def get(self, url: str, params=None, timeout: int = 0, stream: bool = False):
        if "Calendar.aspx" in url:
            self.calls.append(url)
            return FakeResponse(text=_page(self.calendar_rows))
        if "webapi.legistar.com" in url:
            self.calls.append(url)
            return FakeResponse(payload=self.events)
        return super().get(url, params, timeout, stream)


def _archive(meetings_dir: Path, slug: str, day: str, event_id: int = 1,
             complete: bool = True) -> Path:
    mdir = meetings_dir / slug
    mdir.mkdir(parents=True)
    Manifest(slug=slug, title=slug, date=day, body="City Council Regular Meeting",
             video_page_url="https://v", castus_id="c", mp4_url="https://m",
             legistar_event_id=event_id, legistar_url="https://l",
             agenda_url="https://a.pdf", minutes_url=None,
             audio_asset_tag=f"audio-{slug}").save(mdir)
    if complete:
        (mdir / "agenda.pdf").write_bytes(b"%PDF")
        (mdir / "agenda-preview.md").write_text("preview")
        (mdir / "summary.md").write_text("summary")
        (mdir / "transcript").mkdir()
        (mdir / "transcript" / "whisper-medium.txt").write_text("words")
        manifest = Manifest.load(mdir)
        manifest.status["has_audio_asset"] = True
        manifest.save(mdir)
    return mdir


def test_coverage_clean_archive_has_no_gaps(tmp_path, capsys) -> None:
    meetings, upcoming = tmp_path / "meetings", tmp_path / "upcoming"
    meetings.mkdir()
    _archive(meetings, "2026-09-10-city-council-meeting", "2026-09-10")
    session = CalendarSession(
        _row("gridCalendar", 0, "City Council Regular Meeting", "9/10/2026",
             agenda=True), [])
    rc = coverage(date(2026, 4, 1), meetings, upcoming, session,
                  today=date(2026, 9, 14), strict=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "0 gap(s)" in out
    assert "archived 1/1" in out


def test_coverage_flags_a_past_meeting_that_never_got_archived(tmp_path, capsys) -> None:
    """The failure nothing else notices: scheduled, happened, no folder."""
    meetings, upcoming = tmp_path / "meetings", tmp_path / "upcoming"
    meetings.mkdir()
    session = CalendarSession(
        _row("gridCalendar", 0, "City Council Regular Meeting", "9/10/2026",
             agenda=True), [])
    rc = coverage(date(2026, 4, 1), meetings, upcoming, session,
                  today=date(2026, 9, 25), strict=True)
    captured = capsys.readouterr()
    assert rc == 1
    assert "1 gap(s)" in captured.out
    assert "2026-09-10" in captured.err and "no archive folder" in captured.err


def test_coverage_holds_a_fresh_meeting_in_the_grace_period(tmp_path, capsys) -> None:
    """The video posts a day or two late; that must not cry wolf."""
    meetings, upcoming = tmp_path / "meetings", tmp_path / "upcoming"
    meetings.mkdir()
    session = CalendarSession(
        _row("gridCalendar", 0, "City Council Regular Meeting", "9/10/2026",
             agenda=True), [])
    rc = coverage(date(2026, 4, 1), meetings, upcoming, session,
                  today=date(2026, 9, 12), strict=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Pending (1" in out and "0 gap(s)" in out


def test_coverage_flags_missing_artifacts(tmp_path, capsys) -> None:
    meetings, upcoming = tmp_path / "meetings", tmp_path / "upcoming"
    meetings.mkdir()
    mdir = _archive(meetings, "2026-09-10-city-council-meeting", "2026-09-10",
                    complete=False)
    (mdir / "agenda.pdf").write_bytes(b"%PDF")
    session = CalendarSession(
        _row("gridCalendar", 0, "City Council Regular Meeting", "9/10/2026",
             agenda=True), [])
    rc = coverage(date(2026, 4, 1), meetings, upcoming, session,
                  today=date(2026, 9, 14), strict=True)
    captured = capsys.readouterr()
    assert rc == 1
    for label in ("preview", "summary", "transcript", "audio asset"):
        assert label in captured.err


def test_coverage_finds_an_older_gap_the_month_calendar_cannot_see(
        tmp_path, capsys) -> None:
    """The calendar page shows one month; the API backs up the earlier ones."""
    meetings, upcoming = tmp_path / "meetings", tmp_path / "upcoming"
    meetings.mkdir()
    session = CalendarSession(
        _row("gridCalendar", 0, "City Council Regular Meeting", "9/10/2026",
             agenda=True),
        [{"EventId": 1226, "EventDate": "2026-08-13T00:00:00",
          "EventBodyName": "City Council Regular Meeting",
          "EventAgendaFile": "https://a.pdf", "EventMinutesFile": None}])
    rc = coverage(date(2026, 4, 1), meetings, upcoming, session,
                  today=date(2026, 9, 14), strict=True)
    err = capsys.readouterr().err
    assert rc == 1
    assert "2026-08-13" in err


def test_coverage_reports_upcoming_preview_state(tmp_path, capsys) -> None:
    meetings, upcoming = tmp_path / "meetings", tmp_path / "upcoming"
    meetings.mkdir()
    pdir = upcoming / "2026-09-24-city-council-regular-meeting"
    pdir.mkdir(parents=True)
    (pdir / "agenda-preview.md").write_text("preview")
    session = CalendarSession(
        _row("gridCalendar", 0, "City Council Regular Meeting", "9/24/2026",
             agenda=True)
        + _row("gridCalendar", 1, "City Council Special Session", "9/29/2026",
               time="12:00 PM"), [])
    rc = coverage(date(2026, 4, 1), meetings, upcoming, session,
                  today=date(2026, 9, 20), strict=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "preview built" in out and "4d out" in out
    assert "agenda NOT posted, preview pending, 9d out" in out


def test_coverage_treats_an_empty_calendar_as_a_broken_scrape(tmp_path, capsys) -> None:
    """The alarm must not fail open when Legistar changes its markup."""
    meetings, upcoming = tmp_path / "meetings", tmp_path / "upcoming"
    meetings.mkdir()
    session = CalendarSession("", [])
    rc = coverage(date(2026, 4, 1), meetings, upcoming, session,
                  today=date(2026, 9, 14), strict=True)
    assert rc == 1
    assert "schedule scrape is probably broken" in capsys.readouterr().err


def test_coverage_explains_why_votes_are_empty(tmp_path, capsys) -> None:
    meetings, upcoming = tmp_path / "meetings", tmp_path / "upcoming"
    meetings.mkdir()
    _archive(meetings, "2026-09-10-city-council-meeting", "2026-09-10", event_id=42)
    session = CalendarSession(
        _row("gridCalendar", 0, "City Council Regular Meeting", "9/10/2026",
             agenda=True),
        [{"EventId": 42, "EventDate": "2026-09-10T00:00:00",
          "EventBodyName": "City Council Regular Meeting",
          "EventAgendaFile": "https://a.pdf", "EventMinutesFile": None}])
    coverage(date(2026, 4, 1), meetings, upcoming, session,
             today=date(2026, 9, 14))
    assert "Awaiting Final minutes: 1 of 1" in capsys.readouterr().out
