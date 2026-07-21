import json
from pathlib import Path
from typing import Any

import pytest
import requests

from hsvcc import (RollCall, _get_with_retry, download_file, extract_minutes_votes,
                   extract_votes, find_matter, parse_minutes_rollcall)

CONSENT_MINUTES = """
20. NEW BUSINESS ITEMS FOR CONSIDERATION OR ACTION
A motion was made by President Meredith, seconded by President Pro Tem Robinson, to
approve the Consent Agenda. The motion carried by the following vote:
Aye: Meredith, Robinson, Kling, Keith, and Little
Nay: None
a. Resolution authorizing travel expenses.
Resolution No. 23-667
This New Business for Consideration or Action was approved consent items.
w. Resolution authorizing the Mayor to enter into a PSC with FLOCK Group, Inc.
Resolution No. 23-689
This New Business for Consideration or Action was approved.
x. Resolution authorizing a Special Employee Agreement.
Resolution No. 23-691
This New Business for Consideration or Action was approved.
"""

INDIVIDUAL_MINUTES = """
9a. Ordinance rezoning a parcel.
Ordinance No. 26-491
President Pro Tem Robinson moved to approve the Ordinance, which motion was duly
seconded by Councilmember Kling. President Meredith called for a roll-call vote on
the above motion, and the following vote resulted:
Aye: Meredith, Robinson, and Kling
Nay: Little
9b. Another item.
Resolution No. 26-492
"""


def test_rollcall_consent_item_uses_consent_agenda_vote() -> None:
    rc = parse_minutes_rollcall(CONSENT_MINUTES, "23-689")
    assert rc == RollCall(True, ["Meredith", "Robinson", "Kling", "Keith", "Little"], [])


def test_rollcall_individual_item_captures_aye_and_nay() -> None:
    rc = parse_minutes_rollcall(INDIVIDUAL_MINUTES, "26-491")
    assert rc is not None and rc.consent is False
    assert rc.aye == ["Meredith", "Robinson", "Kling"]
    assert rc.nay == ["Little"]


def test_rollcall_none_when_no_vote_recorded() -> None:
    assert parse_minutes_rollcall("Resolution No. 99-999\nwas approved.\n", "99-999") is None


def test_rollcall_none_when_number_absent() -> None:
    assert parse_minutes_rollcall(CONSENT_MINUTES, "24-281") is None


def test_extract_minutes_votes_lists_all_numbers_in_order() -> None:
    items = extract_minutes_votes(CONSENT_MINUTES)
    assert [i["number"] for i in items] == ["23-667", "23-689", "23-691"]
    assert all(i["vote"] is not None and i["vote"]["consent"] for i in items)


def test_extract_minutes_votes_null_vote_when_no_rollcall() -> None:
    items = extract_minutes_votes(INDIVIDUAL_MINUTES)
    assert items[0]["number"] == "26-491"
    assert items[0]["vote"] == {"consent": False,
                                "aye": ["Meredith", "Robinson", "Kling"], "nay": ["Little"]}
    assert items[1] == {"number": "26-492", "vote": None}


class FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        pass


class FakeSession:
    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.calls: list[tuple[str, Any]] = []

    def get(self, url: str, params: Any = None, timeout: int = 0) -> FakeResponse:
        self.calls.append((url, params))
        return FakeResponse(self.payload)


def test_find_matter_prefers_exact_number_not_prefix() -> None:
    s = FakeSession([
        {"MatterId": 1, "MatterTitle": "Resolution ... Resolution No. 23-6890"},
        {"MatterId": 2, "MatterTitle": "Resolution ... Resolution No. 23-689"},
    ])
    m = find_matter("23-689", s)  # type: ignore[arg-type]
    assert m is not None and m["MatterId"] == 2
    assert "substringof('No. 23-689',MatterTitle)" in str(s.calls[0][1])


class _Resp:
    """Response stub whose raise_for_status() mimics requests' HTTPError."""

    def __init__(self, status: int, payload: Any = None) -> None:
        self.status_code = status
        self._payload = payload

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            err = requests.HTTPError(f"{self.status_code} error")
            err.response = self  # type: ignore[assignment]
            raise err


class _SeqSession:
    """Yields queued _Resp objects (or raises queued exceptions) per get()."""

    def __init__(self, seq: list[Any]) -> None:
        self._seq = list(seq)
        self.calls = 0

    def get(self, url: str, params: Any = None, stream: bool = False,
            timeout: int = 0) -> Any:
        self.calls += 1
        item = self._seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _no_sleep(_seconds: float) -> None:
    pass


def test_get_with_retry_recovers_from_transient_404() -> None:
    s = _SeqSession([_Resp(404), _Resp(200, {"ok": True})])
    resp = _get_with_retry("http://x", s, sleep=_no_sleep)  # type: ignore[arg-type]
    assert resp.json() == {"ok": True}
    assert s.calls == 2


def test_get_with_retry_retries_5xx_then_gives_up() -> None:
    s = _SeqSession([_Resp(503), _Resp(503), _Resp(503)])
    with pytest.raises(requests.HTTPError):
        _get_with_retry("http://x", s, attempts=3, sleep=_no_sleep)  # type: ignore[arg-type]
    assert s.calls == 3


def test_get_with_retry_does_not_retry_forbidden() -> None:
    s = _SeqSession([_Resp(403), _Resp(200, {"ok": True})])
    with pytest.raises(requests.HTTPError):
        _get_with_retry("http://x", s, sleep=_no_sleep)  # type: ignore[arg-type]
    assert s.calls == 1  # a 403 is not transient -> no retry


def test_get_with_retry_retries_connection_errors() -> None:
    s = _SeqSession([requests.ConnectionError("boom"), _Resp(200, {"ok": True})])
    resp = _get_with_retry("http://x", s, sleep=_no_sleep)  # type: ignore[arg-type]
    assert resp.json() == {"ok": True}
    assert s.calls == 2


def _write_manifest(mdir: Path, **overrides: Any) -> None:
    mdir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "slug": mdir.name, "title": "Test Meeting", "date": "2026-06-11",
        "body": None, "video_page_url": "", "castus_id": "", "mp4_url": "",
        "legistar_event_id": 1222, "legistar_url": None, "agenda_url": None,
        "minutes_url": None, "audio_asset_tag": "",
    }
    manifest.update(overrides)
    (mdir / "meeting.json").write_text(json.dumps(manifest))


class _StreamResp:
    """Streaming response stub usable as a context manager for download_file."""

    def __init__(self, status: int, body: bytes = b"") -> None:
        self.status_code = status
        self._body = body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            err = requests.HTTPError(f"{self.status_code} error")
            err.response = self  # type: ignore[assignment]
            raise err

    def iter_content(self, chunk_size: int = 0) -> Any:
        yield self._body

    def __enter__(self) -> "_StreamResp":
        return self

    def __exit__(self, *exc: Any) -> None:
        pass


def test_download_file_retries_transient_error(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hsvcc.time.sleep", _no_sleep)
    s = _SeqSession([_StreamResp(503), _StreamResp(200, b"PDFDATA")])
    dest = tmp_path / "out" / "minutes.pdf"
    download_file("http://x", dest, s)  # type: ignore[arg-type]
    assert dest.read_bytes() == b"PDFDATA"
    assert s.calls == 2  # first 503 retried, second succeeded


def test_extract_votes_skips_meeting_when_legistar_flaky(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hsvcc.time.sleep", _no_sleep)
    meetings = tmp_path / "meetings"
    _write_manifest(meetings / "2026-06-11-city-council-meeting")
    # Legistar 404s on every retry -> the opportunistic lookup ultimately fails.
    s = _SeqSession([_Resp(404)] * 10)
    rc = extract_votes([], meetings, s)  # type: ignore[arg-type]
    assert rc == 0  # a flaky Legistar lookup must not fail the whole run
