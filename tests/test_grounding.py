"""Checks on grounding.py, anchored to the two defects that reached the site."""
from grounding import (agenda_items, report, unsupported_figures,
                       unsupported_names, uncovered_items)

# Shaped like a real agenda-preview.md, including the wide runs of spaces
# Legistar produces and the trailing sponsor annotation.
PREVIEW = """# Agenda preview - City Council Regular Meeting, 2026-08-27

### 9. PUBLIC HEARINGS TO BE HELD

- 2026-874     Public Hearing for removal of a public nuisance at 4704 Cavett Dr. NW. *(sponsors: Community Development)*
- 2026-879       Public Hearing on the zoning of 24.67 acres of land lying on the north side of University Drive. *(sponsors: Planning)*

### 20. NEW BUSINESS ITEMS FOR CONSIDERATION OR ACTION

- 2026-900     Resolution authorizing an Agreement with Strozier Construction Company, Inc. for the Mill Creek Facade Improvement Grant Program. *(sponsors: Community Development)*
- 2026-911       Resolution authorizing a Memorandum of Understanding with the Federal Bureau of Investigation to establish the Tennessee Valley Threat Assessment Team. *(sponsors: Police)*
- 2026-893      Resolution authorizing travel expenses. *(sponsors: Finance)*
- 2026-899      Resolution authorizing the City Council. *(sponsors: Legal)*
"""

# Mentions every item above, so nothing should be reported as uncovered.
COMPLETE = (
    "- nuisance at 4704 Cavett Dr. NW\n"
    "- zoning of 24.67 acres on University Drive\n"
    "- Strozier Construction, Mill Creek Facade program\n"
    "- Memorandum with the Federal Bureau of Investigation, Tennessee Valley "
    "Threat Assessment Team\n"
    "- travel expenses\n"
)


def test_agenda_items_parses_ids_and_strips_sponsors() -> None:
    items = agenda_items(PREVIEW)
    assert [i for i, _ in items] == ["2026-874", "2026-879", "2026-900",
                                     "2026-911", "2026-893", "2026-899"]
    assert "sponsors" not in " ".join(t for _, t in items)


# ---------------------------------------------------------------- figures

def test_flags_a_fabricated_figure() -> None:
    """The 2026-05-14 draft invented a $1,334,500 architect fee."""
    sources = "Agreement for Architectural Services with Nola|VanPeursem Architects."
    assert unsupported_figures("the contract for $1,334,500.", sources) == ["$1,334,500"]


def test_accepts_verbatim_figures() -> None:
    sources = "Total Cost: $175,000.00 against $53,617,414.27 in expenditures"
    assert unsupported_figures("a $175,000.00 contract, $53,617,414.27 total",
                               sources) == []


def test_ignores_comma_and_space_formatting() -> None:
    """Expenditure tables render amounts as '$    13,999,801.48'."""
    assert unsupported_figures("costs $13,999,801.48",
                               "GENERAL FUND $    13,999,801.48") == []


# ------------------------------------------------------------------ names

def test_flags_a_name_absent_from_sources() -> None:
    got = unsupported_names("awarded to Ferndale Paving Partners.",
                            "awarded to Strozier Construction")
    assert got == ["Ferndale Paving Partners"]


def test_trailing_sentence_period_is_not_a_new_name() -> None:
    assert unsupported_names("demolition at Barry St. NW.",
                             "nuisance at 4204 Barry St. NW") == []


def test_typographic_apostrophe_matches_straight_one() -> None:
    assert unsupported_names("the City's SCADA panels",
                             "services for the City’s SCADA") == []


def test_possessive_matches_the_bare_name() -> None:
    assert unsupported_names("the Von Braun Center's expansion",
                             "at the Von Braun Center") == []


def test_recombined_wording_is_not_reported() -> None:
    """Every word present, phrasing new - a restatement, not an invention."""
    assert unsupported_names("the Capital Improvements Fund",
                             "2014 CAPITAL IMPROVEMENTS fund row") == []


# --------------------------------------------------------------- coverage

def test_uncovered_items_names_what_a_thin_summary_dropped() -> None:
    """The shipped 2026-08-25 summary covered 6 of 85 items."""
    thin = "- The council will vote on rezoning 24.67 acres near University Drive."
    missed = {i for i, _ in uncovered_items(thin, PREVIEW)}
    assert "2026-911" in missed          # the FBI threat-assessment MOU
    assert "2026-900" in missed          # the Mill Creek facade contract
    assert "2026-879" not in missed      # the rezoning it did cover


def test_full_coverage_reports_nothing() -> None:
    assert uncovered_items(COMPLETE, PREVIEW) == []


def test_item_of_pure_boilerplate_is_skipped_not_flagged() -> None:
    """2026-899 is nothing but agenda boilerplate, so it cannot be judged.

    2026-893 ("travel expenses") IS reported against an empty summary, and that
    is correct: those words are rare on this agenda, so their absence is real
    evidence the item went unmentioned.
    """
    missed = {i for i, _ in uncovered_items("", PREVIEW)}
    assert "2026-899" not in missed
    assert "2026-893" in missed


# ----------------------------------------------------------------- report

def test_report_can_skip_names_for_notes() -> None:
    text = "Ferndale Paving Partners did the work."
    assert report(text, "nothing relevant here")
    assert report(text, "nothing relevant here", check_names=False) == []


def test_report_is_empty_when_everything_is_grounded() -> None:
    assert report(COMPLETE, PREVIEW, PREVIEW) == []
