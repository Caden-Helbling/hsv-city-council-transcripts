from typing import Any

from hsvcc import RollCall, extract_minutes_votes, find_matter, parse_minutes_rollcall

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
