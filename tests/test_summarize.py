from datetime import date
from pathlib import Path

import pytest

from summarize_agendas import (MAX_ATTEMPTS, hash_input, lead_and_rest,
                               render_summary_md, source_hash,
                               structure_problems, structure_report,
                               summarize, summary_is_current, top_funds,
                               TOP_FUNDS_HEADING)

TODAY = date(2026, 8, 18)
PREVIEW = "# Agenda preview\n\n- item\n"


def shaped(lead: str = "- The vote that matters",
           rest: str = "- A routine appointment") -> str:
    """The shape prompts/laymans-summary.md asks for: a lead, then groups.

    Test generators return this so structure_problems stays quiet and the
    off-shape retry does not fire in tests that count generate() calls.
    """
    return (f"### What matters most\n\n{lead}\n\n"
            f"### Routine business\n\n{rest}\n")


def _make_upcoming(tmp_path: Path) -> Path:
    pdir = tmp_path / "upcoming" / "2026-08-27-city-council-regular-meeting"
    pdir.mkdir(parents=True)
    (pdir / "agenda-preview.md").write_text(PREVIEW, encoding="utf-8")
    return pdir


def test_skips_without_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SLAYDEN_API_TOKEN", raising=False)
    pdir = _make_upcoming(tmp_path)
    assert summarize(tmp_path / "upcoming", today=TODAY,
                     generate=lambda _: pytest.fail("should not call the API")) == 0
    assert not (pdir / "summary.md").exists()


def test_generates_summary_with_hash_marker(tmp_path: Path,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLAYDEN_API_TOKEN", "test-key")
    pdir = _make_upcoming(tmp_path)
    assert summarize(tmp_path / "upcoming", today=TODAY,
                     generate=lambda _: shaped("- The city plans X")) == 0
    text = (pdir / "summary.md").read_text(encoding="utf-8")
    assert "- The city plans X" in text
    assert f"source-sha256: {source_hash(hash_input(PREVIEW))}" in text
    assert "AI-generated" in text


def test_skips_when_summary_matches_preview_hash(tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLAYDEN_API_TOKEN", "test-key")
    pdir = _make_upcoming(tmp_path)
    (pdir / "summary.md").write_text(render_summary_md("- old", hash_input(PREVIEW), "2026-08-11"),
                                     encoding="utf-8")
    assert summarize(tmp_path / "upcoming", today=TODAY,
                     generate=lambda _: pytest.fail("hash unchanged; must not regen")) == 0


def test_regenerates_when_agenda_amended(tmp_path: Path,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLAYDEN_API_TOKEN", "test-key")
    pdir = _make_upcoming(tmp_path)
    (pdir / "summary.md").write_text(
        render_summary_md("- old", hash_input("different preview"), "2026-08-11"), encoding="utf-8")
    assert not summary_is_current(pdir / "summary.md", hash_input(PREVIEW))
    summarize(tmp_path / "upcoming", today=TODAY, generate=lambda _: shaped("- new"))
    assert "- new" in (pdir / "summary.md").read_text(encoding="utf-8")


def test_generation_failure_is_nonfatal(tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLAYDEN_API_TOKEN", "test-key")
    pdir = _make_upcoming(tmp_path)

    def boom(_: str) -> str:
        raise RuntimeError("api down")

    assert summarize(tmp_path / "upcoming", today=TODAY, generate=boom) == 0
    assert not (pdir / "summary.md").exists()


def test_attachment_excerpts_enrich_source_and_hash(tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLAYDEN_API_TOKEN", "test-key")
    pdir = _make_upcoming(tmp_path)
    # summary was generated from the preview alone...
    (pdir / "summary.md").write_text(render_summary_md("- old", hash_input(PREVIEW), "2026-08-11"),
                                     encoding="utf-8")
    # ...then attachment excerpts arrive: hash changes, summary regenerates richer
    (pdir / "agenda-attachments.md").write_text(
        "# Agenda attachment excerpts\n\n## Expenditures - Complete\n\n"
        "Grand Total $30,015,087.43\n", encoding="utf-8")
    seen: list[str] = []

    def gen(source: str) -> str:
        seen.append(source)
        return shaped("- richer bullet")

    assert summarize(tmp_path / "upcoming", today=TODAY, generate=gen) == 0
    assert len(seen) == 1
    assert "$30,015,087.43" in seen[0]      # excerpts reach the LLM input
    assert "Agenda preview" in seen[0]      # preview still included
    assert "- richer bullet" in (pdir / "summary.md").read_text(encoding="utf-8")


def _make_meeting(tmp_path: Path, slug: str, with_preview: bool = True,
                  with_summary: bool = False) -> Path:
    mdir = tmp_path / "meetings" / slug
    mdir.mkdir(parents=True)
    if with_preview:
        (mdir / "agenda-preview.md").write_text(PREVIEW, encoding="utf-8")
    if with_summary:
        (mdir / "summary.md").write_text(
            render_summary_md("- archived", hash_input(PREVIEW), "2026-08-11"), encoding="utf-8")
    return mdir


def test_backfills_past_meeting_missing_summary(tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLAYDEN_API_TOKEN", "test-key")
    missed = _make_meeting(tmp_path, "2026-08-13-city-council-meeting")
    done = _make_meeting(tmp_path, "2026-07-23-city-council-meeting", with_summary=True)
    no_preview = _make_meeting(tmp_path, "2026-04-09-city-council-meeting",
                               with_preview=False)
    calls: list[str] = []

    def gen(preview: str) -> str:
        calls.append(preview)
        return shaped("- backfilled bullet")

    assert summarize(tmp_path / "upcoming", tmp_path / "meetings",
                     today=TODAY, generate=gen) == 0
    assert len(calls) == 1  # only the meeting that missed its summary
    assert "- backfilled bullet" in (missed / "summary.md").read_text(encoding="utf-8")
    assert "- archived" in (done / "summary.md").read_text(encoding="utf-8")
    assert not (no_preview / "summary.md").exists()


def test_backlog_and_upcoming_processed_in_one_run(tmp_path: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLAYDEN_API_TOKEN", "test-key")
    up = _make_upcoming(tmp_path)
    missed = _make_meeting(tmp_path, "2026-08-13-city-council-meeting")
    assert summarize(tmp_path / "upcoming", tmp_path / "meetings",
                     today=TODAY, generate=lambda _: shaped("- bullet")) == 0
    assert (up / "summary.md").exists()
    assert (missed / "summary.md").exists()


def _make_past(tmp_path: Path, name: str = "2026-05-14-city-council-meeting") -> Path:
    pdir = tmp_path / "meetings" / name
    pdir.mkdir(parents=True)
    (pdir / "agenda-preview.md").write_text(PREVIEW, encoding="utf-8")
    return pdir


def test_past_meeting_summary_is_never_regenerated(tmp_path: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """A stale hash (e.g. after a prompt change) must not rewrite the archive."""
    monkeypatch.setenv("SLAYDEN_API_TOKEN", "test-key")
    pdir = _make_past(tmp_path)
    (pdir / "summary.md").write_text(
        render_summary_md("- as published", hash_input("a different prompt"), "2026-05-15"),
        encoding="utf-8")
    assert summarize(tmp_path / "upcoming", tmp_path / "meetings", today=TODAY,
                     generate=lambda _: pytest.fail("must not regenerate a past meeting")) == 0
    assert "- as published" in (pdir / "summary.md").read_text(encoding="utf-8")


def test_past_meeting_without_summary_is_backfilled(tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLAYDEN_API_TOKEN", "test-key")
    pdir = _make_past(tmp_path)
    assert summarize(tmp_path / "upcoming", tmp_path / "meetings", today=TODAY,
                     generate=lambda _: shaped("- backfilled bullet")) == 0
    assert "- backfilled bullet" in (pdir / "summary.md").read_text(encoding="utf-8")


def test_upcoming_still_regenerates_on_prompt_change(tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLAYDEN_API_TOKEN", "test-key")
    pdir = _make_upcoming(tmp_path)
    (pdir / "summary.md").write_text(
        render_summary_md("- old", hash_input("a different prompt"), "2026-08-11"),
        encoding="utf-8")
    assert summarize(tmp_path / "upcoming", tmp_path / "meetings", today=TODAY,
                     generate=lambda _: shaped("- regenerated")) == 0
    assert "- regenerated" in (pdir / "summary.md").read_text(encoding="utf-8")


# --------------------------------------------------------------- output shape

def test_shaped_summary_has_no_structure_problems() -> None:
    assert structure_problems(shaped()) == []


def test_flat_bullet_list_is_reported_as_off_shape() -> None:
    problems = structure_problems("- one\n- two\n- three\n")
    assert any("### headings" in p for p in problems)


def test_boilerplate_opener_is_reported() -> None:
    body = shaped("- The council will vote to rezone 12 acres")
    problems = structure_problems(body)
    assert any("The council" in p for p in problems)


def test_bolded_boilerplate_opener_is_still_reported() -> None:
    """The prefix hides behind bold just as easily: **The council will vote**."""
    body = shaped("- **The council will vote** on a rezoning")
    assert any("The council" in p for p in structure_problems(body))


def test_council_filler_after_the_dash_is_reported() -> None:
    body = shaped("- **Budget amendment** — the council amends the budget")
    assert any("after the dash" in p for p in structure_problems(body))


def test_volunteered_item_number_is_reported() -> None:
    """Misattribution is invisible to grounding, so the citation itself is banned."""
    body = shaped("- **TIF D8 hearing** — a hearing on a new district "
                  "(Ordinance 26-761).")
    assert any("ordinance/resolution number" in p for p in structure_problems(body))


def test_trailing_item_number_is_reported() -> None:
    body = shaped("- **Travel expenses** — travel expenses are authorized, "
                  "Resolution No. 26-796.")
    assert any("ordinance/resolution number" in p for p in structure_problems(body))


FUND_TABLE = """# Agenda attachment excerpts

## Expenditures - Complete

City Cost Amount: $ 42,341,723.17

FUND ACCOUNT
         FUND NAME                                 AMOUNT
  1000    GENERAL FUND                    $    11,276,708.72
  1005    HEALTH & LIFE BENEFITS          $      (400,608.86)
  2101    COMMUNITY DEV COVID             $              -
  3010    6.5 MILL SCHOOL PROPERTY TAX    $     9,068,273.03
  3020    1990 CAPITAL IMPROVEMENTS       $     4,134,468.63
  6000    WATER POLLUTION CONTROL         $     3,443,192.04
"""


def test_top_funds_ranks_the_table_deterministically() -> None:
    """The model ranked this wrong in four of five drafts; the parser cannot."""
    assert top_funds(FUND_TABLE) == [
        ("GENERAL FUND", "$11,276,708.72"),
        ("6.5 MILL SCHOOL PROPERTY TAX", "$9,068,273.03"),
        ("1990 CAPITAL IMPROVEMENTS", "$4,134,468.63"),
    ]


def test_top_funds_skips_zero_and_credit_rows() -> None:
    names = [n for n, _ in top_funds(FUND_TABLE, n=99)]
    assert "COMMUNITY DEV COVID" not in names     # "-" is not an expenditure
    assert "HEALTH & LIFE BENEFITS" not in names  # a credit is not "largest"


def test_top_funds_is_empty_without_a_table() -> None:
    assert top_funds("no fund table here") == []


def test_computed_ranking_reaches_the_llm_input(tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLAYDEN_API_TOKEN", "test-key")
    pdir = _make_upcoming(tmp_path)
    (pdir / "agenda-attachments.md").write_text(FUND_TABLE, encoding="utf-8")
    seen: list[str] = []

    def gen(source: str) -> str:
        seen.append(source)
        return shaped("- **Expenditures** — $11,276,708.72, $9,068,273.03, "
                      "$4,134,468.63")

    assert summarize(tmp_path / "upcoming", today=TODAY, generate=gen) == 0
    assert TOP_FUNDS_HEADING in seen[0]
    assert seen[0].index("GENERAL FUND $11,276,708.72") > seen[0].index(TOP_FUNDS_HEADING)


def test_draft_omitting_a_top_fund_loses_to_one_that_keeps_it(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLAYDEN_API_TOKEN", "test-key")
    pdir = _make_upcoming(tmp_path)
    (pdir / "agenda-attachments.md").write_text(FUND_TABLE, encoding="utf-8")
    bodies = iter([
        # drops the largest fund for a smaller one - the observed live failure
        shaped("- **Expenditures** — $9,068,273.03, $4,134,468.63, $3,443,192.04"),
        shaped("- **Expenditures** — $11,276,708.72, $9,068,273.03, $4,134,468.63"),
        shaped("- **Expenditures** — $9,068,273.03 only"),
    ])
    assert summarize(tmp_path / "upcoming", today=TODAY,
                     generate=lambda _: next(bodies)) == 0
    assert "$11,276,708.72" in (pdir / "summary.md").read_text(encoding="utf-8")


def test_stated_count_is_reported() -> None:
    """'five separate properties' above a list of four — an observed failure."""
    body = shaped("- **Rezonings** — hearings are set on five separate properties")
    assert any("state a count" in p for p in structure_problems(body))


def test_bare_count_before_a_verb_is_reported() -> None:
    """'three are appointed to X and Y' — was four, and read as a total."""
    body = shaped("- **Boards** — three are appointed or reappointed to the "
                  "Human Relations Commission and City Tree Commission")
    assert any("state a count" in p for p in structure_problems(body))


def test_acreages_and_terms_are_not_mistaken_for_counts() -> None:
    body = shaped("- **536.68 acres east of US Hwy 72 E** — rezoned to Residence 1",
                  "- **Beautification Board** — three-year terms expiring in 2029")
    assert structure_problems(body) == []


def test_all_caps_source_text_is_reported() -> None:
    body = shaped("- **Expenditures** — drawn from the 6.5 MILL SCHOOL PROPERTY "
                  "TAX fund")
    assert any("ALL-CAPS" in p for p in structure_problems(body))


def test_short_acronyms_are_not_mistaken_for_shouting() -> None:
    body = shaped('- **TIF D8** — a hearing on the district, per US Hwy 431',
                  "- **FSA administration** — an amendment with WageWorks, LLC")
    assert structure_problems(body) == []


def test_amended_ordinance_number_is_allowed() -> None:
    """The agenda ties 89-79 to the salary plan; that citation is not a guess."""
    body = shaped("- **Public safety salary schedule** — amends Ordinance No. "
                  "89-79, the classification and salary plan, to add pay rates.")
    assert structure_problems(body) == []


def test_overlong_lead_is_reported() -> None:
    lead = "\n".join(f"- item {i}" for i in range(8))
    problems = structure_problems(shaped(lead))
    assert any("lead has 8 bullets" in p for p in problems)


def test_lead_length_not_judged_without_groups() -> None:
    """A body with no groups is already reported; do not pile on a second flag."""
    flat = "### What matters most\n\n" + "\n".join(f"- item {i}" for i in range(9))
    assert not any("bullets" in p for p in structure_problems(flat))


def test_renamed_lead_heading_is_reported() -> None:
    body = "### Highlights\n\n- a\n\n### Routine business\n\n- b\n"
    problems = structure_problems(body)
    assert any("expected '### What matters most'" in p for p in problems)


def test_lead_and_rest_splits_at_second_heading() -> None:
    lead, rest = lead_and_rest(shaped("- lead bullet", "- group bullet"))
    assert "lead bullet" in lead and "group bullet" not in lead
    assert rest.startswith("### Routine business")
    assert "group bullet" in rest


def test_lead_and_rest_keeps_an_ungrouped_body_whole() -> None:
    lead, rest = lead_and_rest("- one\n- two\n")
    assert lead == "- one\n- two"
    assert rest == ""


def test_off_shape_summary_is_retried_then_published_anyway(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Shape earns one retry but never blocks: accurate and ugly beats nothing."""
    monkeypatch.setenv("SLAYDEN_API_TOKEN", "test-key")
    pdir = _make_upcoming(tmp_path)
    calls: list[str] = []

    def flat(_: str) -> str:
        calls.append("call")
        return "- The council will vote on item one\n"

    assert summarize(tmp_path / "upcoming", today=TODAY, generate=flat) == 0
    assert len(calls) == MAX_ATTEMPTS            # bounded retries, then publish
    text = (pdir / "summary.md").read_text(encoding="utf-8")
    assert "The council will vote on item one" in text


def test_weight_ranks_two_drafts_with_the_same_problem_kind() -> None:
    """The bug this caught: both drafts flagged 'the council' filler, one 38
    bullets' worth and one 8, and an empty-or-not test picked the worse."""
    worse = shaped("- **A** — the council does a", "- **B** — the council does b")
    better = shaped("- **A** — the council does a", "- **B** — adopts b")
    worse_problems, worse_weight = structure_report(worse)
    better_problems, better_weight = structure_report(better)
    assert len(worse_problems) == len(better_problems) == 1
    assert better_weight < worse_weight


def test_missing_shape_outweighs_any_number_of_per_bullet_nits() -> None:
    flat = "- **A** — the council does a\n"
    nitty = shaped("- **A** — the council does a", "- **B** — the council does b")
    assert structure_report(nitty)[1] < structure_report(flat)[1]


def test_less_bad_draft_wins_when_both_are_off_shape(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLAYDEN_API_TOKEN", "test-key")
    pdir = _make_upcoming(tmp_path)
    bodies = iter([
        "- The council will vote on one\n- The council will vote on two\n",
        shaped("- **Budget** — the council adopts it"),   # off-shape, but barely
        "- The council will vote on three\n",
    ])
    assert summarize(tmp_path / "upcoming", today=TODAY,
                     generate=lambda _: next(bodies)) == 0
    text = (pdir / "summary.md").read_text(encoding="utf-8")
    assert "**Budget**" in text
    assert "The council will vote on one" not in text


def test_coverage_outranks_shape_when_choosing_a_draft(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A well-shaped draft that drops an item loses to an ugly complete one."""
    monkeypatch.setenv("SLAYDEN_API_TOKEN", "test-key")
    pdir = tmp_path / "upcoming" / "2026-09-10-city-council-regular-meeting"
    pdir.mkdir(parents=True)
    (pdir / "agenda-preview.md").write_text(
        "# Agenda preview\n\n## Topics\n\n"
        "- 2026-999 Ordinance to exempt hearing aids from city sales tax.\n"
        "- 2026-935 Ordinance approving the Vandiver Road culvert.\n",
        encoding="utf-8")
    bodies = iter([
        shaped("- **Vandiver Road culvert** — approves the work"),   # drops 999
        shaped("- **Hearing aid sales tax exemption** — the council exempts them",
               "- **Vandiver Road culvert** — the council approves the work"),
        shaped("- **Vandiver Road culvert** — approves the work"),   # drops 999
    ])
    assert summarize(tmp_path / "upcoming", today=TODAY,
                     generate=lambda _: next(bodies)) == 0
    text = (pdir / "summary.md").read_text(encoding="utf-8")
    assert "Hearing aid sales tax exemption" in text     # complete, though ugly


def test_shaped_retry_is_preferred_over_the_flat_first_attempt(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLAYDEN_API_TOKEN", "test-key")
    pdir = _make_upcoming(tmp_path)
    bodies = iter(["- flat and boilerplate\n", shaped("- properly grouped")])

    assert summarize(tmp_path / "upcoming", today=TODAY,
                     generate=lambda _: next(bodies)) == 0
    text = (pdir / "summary.md").read_text(encoding="utf-8")
    assert "properly grouped" in text
    assert "flat and boilerplate" not in text


def test_shaped_summary_is_generated_once(tmp_path: Path,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLAYDEN_API_TOKEN", "test-key")
    _make_upcoming(tmp_path)
    calls: list[str] = []

    def gen(_: str) -> str:
        calls.append("call")
        return shaped()

    assert summarize(tmp_path / "upcoming", today=TODAY, generate=gen) == 0
    assert len(calls) == 1                       # a good draft is not retried


def test_rendered_summary_nests_groups_under_the_wrapper_heading() -> None:
    text = render_summary_md(shaped(), hash_input(PREVIEW), "2026-09-09")
    assert text.index("## In plain language") < text.index("### What matters most")
    assert "### Routine business" in text
