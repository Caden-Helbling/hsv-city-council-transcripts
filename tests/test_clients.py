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
    assert resolve_mp4_url("abc", s) == "https://cdn/x.mp4"  # type: ignore[arg-type]
    assert s.calls[0][2] == {"file": "abc", "type": "vod", "user": ""}


def test_fetch_captions_returns_vtt_text() -> None:
    s = FakeSession([
        FakeResponse({"response": {"payload": "https://s3/abc.vtt?sig"}}),
        FakeResponse(None, text="WEBVTT\n\n00:00.0 --> 00:01.0\nHi\n"),
    ])
    vtt = fetch_captions("abc", s)  # type: ignore[arg-type]
    assert vtt is not None and vtt.startswith("WEBVTT")


def test_fetch_captions_none_on_error() -> None:
    class Boom(FakeSession):
        def post(self, url: str, json: Any = None, timeout: int = 0) -> FakeResponse:
            raise RuntimeError("api down")
    assert fetch_captions("abc", Boom([])) is None  # type: ignore[arg-type]


def test_fetch_legistar_events_filters_since() -> None:
    s = FakeSession([FakeResponse([{"EventId": 1}])])
    events = fetch_legistar_events(date(2026, 4, 1), s)  # type: ignore[arg-type]
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
