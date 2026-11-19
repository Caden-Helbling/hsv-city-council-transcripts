from datetime import date
from pathlib import Path

from fakes import FakeResponse, FakeSession
from hsvcc import Manifest, discover, match_undated_event


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


# --- council videos whose URL carries no date --------------------------------
# The 2026-11-02 reorganization special session, plus the unrelated oath-of-
# office video posted the same night in the same category.
REORG_URL = ("https://www.huntsvilleal.gov/videos/"
             "huntsville-city-council-2026-27-reorganization-special-session/")
OATH_URL = ("https://www.huntsvilleal.gov/videos/"
            "city-of-huntsville-council-2026-oath-of-office-ceremony-2/")
INTERVIEW_URL = ("https://www.huntsvilleal.gov/videos/"
                 "inside-huntsville-huntsville-botanical-gardens-with-sue-wagner-2/")
UNDATED_PAGES = {
    REORG_URL: ('<script>{"datePublished":"2026-11-03T00:21:56+00:00"}</script>'
                '<h1>Huntsville City Council 2026-27 Reorganization Special Session</h1>'
                '<iframe src="https://cloud.castus.tv/vod/hsv-tv/embed/aaaa1111"></iframe>'),
    OATH_URL: ('<script>{"datePublished":"2026-11-03T02:19:15+00:00"}</script>'
               '<h1>City of Huntsville Council 2026 Oath of Office Ceremony</h1>'
               '<iframe src="https://cloud.castus.tv/vod/hsv-tv/embed/bbbb2222"></iframe>'),
}
NOV_EVENTS = [
    {"EventId": 1405, "EventDate": "2026-11-02T00:00:00",
     "EventBodyName": "City Council Special Session",
     "EventAgendaFile": "https://legistar/special.pdf", "EventMinutesFile": None,
     "EventInSiteURL": "https://legistar/1405"},
    {"EventId": 1232, "EventDate": "2026-11-05T00:00:00",
     "EventBodyName": "City Council Regular Meeting",
     "EventAgendaFile": "https://legistar/regular.pdf", "EventMinutesFile": None,
     "EventInSiteURL": "https://legistar/1232"},
]


class UndatedSession(FakeSession):
    def get(self, url, params=None, timeout=0, stream=False):  # type: ignore[no-untyped-def]
        if "videocategory" in url and "page/" not in url:
            self.calls.append(url)
            return FakeResponse(text="".join(
                f'<a href="{u}">x</a>' for u in (INTERVIEW_URL, OATH_URL, REORG_URL)))
        if url in UNDATED_PAGES:
            self.calls.append(url)
            return FakeResponse(text=UNDATED_PAGES[url])
        if "webapi.legistar.com" in url:
            self.calls.append(url)
            return FakeResponse(payload=NOV_EVENTS)
        return super().get(url, params=params, timeout=timeout, stream=stream)


def test_discover_dates_undated_council_video_from_legistar(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    session = UndatedSession()
    assert discover(date(2026, 4, 1), tmp_path, session) == 0  # type: ignore[arg-type]
    folders = sorted(p.name for p in tmp_path.iterdir())
    assert folders == ["2026-11-02-city-council-2026-27-reorganization-special-session"]
    m = Manifest.load(tmp_path / folders[0])
    assert (m.date, m.legistar_event_id, m.body) == (
        "2026-11-02", 1405, "City Council Special Session")
    assert m.video_page_url == REORG_URL
    # the oath video is named, not silently dropped; the interview is not fetched
    out = capsys.readouterr().out
    assert "warn:" in out and OATH_URL in out
    assert INTERVIEW_URL not in session.calls


def test_discover_undated_video_is_stable_on_rerun(tmp_path: Path) -> None:
    discover(date(2026, 4, 1), tmp_path, UndatedSession())  # type: ignore[arg-type]
    s2 = UndatedSession()
    assert discover(date(2026, 4, 1), tmp_path, s2) == 0  # type: ignore[arg-type]
    assert len(list(tmp_path.iterdir())) == 1
    assert not any(u.endswith(".pdf") or ".vtt" in u for u in s2.calls)


def test_match_undated_event_rules() -> None:
    pub = date(2026, 11, 3)
    title = "Huntsville City Council 2026-27 Reorganization Special Session"
    assert match_undated_event(title, pub, NOV_EVENTS, set())["EventId"] == 1405
    # date already archived -> not claimed a second time
    assert match_undated_event(title, pub, NOV_EVENTS, {"2026-11-02"}) is None
    # outside the lookback window
    assert match_undated_event(title, date(2026, 11, 20), NOV_EVENTS, set()) is None
    # never a meeting that had not happened when the video was published
    assert match_undated_event("Huntsville City Council Meeting", pub, NOV_EVENTS, set()) is None
    assert match_undated_event("City of Huntsville Council 2026 Oath of Office Ceremony",
                               pub, NOV_EVENTS, set()) is None
