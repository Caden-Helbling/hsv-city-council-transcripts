from generate_notes import ATTACHMENT_SECTION_CAP, trim_attachments


def test_trim_attachments_caps_each_section() -> None:
    md = ("# Agenda attachment excerpts\n\nintro\n\n"
          "## Expenditures - Complete\n\n" + ("x" * 5000) + "\n\n"
          "## Small One\n\nGrand Total $5,000\n")
    out = trim_attachments(md)
    assert "## Expenditures - Complete" in out
    assert "[... truncated ...]" in out
    assert "Grand Total $5,000" in out  # small sections pass through whole
    # each section body is bounded
    for body in out.split("## ")[1:]:
        assert len(body) < ATTACHMENT_SECTION_CAP + 200


def test_trim_attachments_passthrough_when_small() -> None:
    md = "# Agenda attachment excerpts\n\n## A\n\nshort\n"
    assert "[... truncated ...]" not in trim_attachments(md)


from pathlib import Path

import generate_notes as gn


def _fake_transcript(n: int = 4000) -> str:
    """One unbroken line of numbered sentences, like real Whisper output."""
    return " ".join(f"Sentence {i} of the council meeting." for i in range(n))


def test_split_transcript_single_chunk_when_it_fits() -> None:
    t = "Short meeting. It adjourned."
    assert gn.split_transcript(t, budget=10_000) == [t]


def test_split_transcript_respects_budget() -> None:
    t = _fake_transcript()
    chunks = gn.split_transcript(t, budget=20_000)
    assert len(chunks) > 1
    assert all(len(c) <= 20_000 for c in chunks)


def test_split_transcript_loses_no_content() -> None:
    """Every sentence must survive into at least one chunk."""
    t = _fake_transcript()
    chunks = gn.split_transcript(t, budget=20_000)
    joined = "\n".join(chunks)
    missing = [i for i in range(4000) if f"Sentence {i} of the council meeting." not in joined]
    assert not missing, f"lost {len(missing)} sentences, e.g. {missing[:5]}"


def test_split_transcript_overlaps_at_seams() -> None:
    t = _fake_transcript()
    chunks = gn.split_transcript(t, budget=20_000, overlap=1_000)
    # the tail of each chunk reappears at the head of the next
    for a, b in zip(chunks, chunks[1:]):
        assert b[:200] in a, "no carry-over between consecutive chunks"


def test_split_transcript_cuts_on_sentence_boundaries() -> None:
    chunks = gn.split_transcript(_fake_transcript(), budget=20_000)
    for c in chunks[:-1]:
        assert c.rstrip().endswith("."), f"cut mid-sentence: {c[-60:]!r}"


def test_split_transcript_terminates_without_sentence_ends() -> None:
    """Pathological input (no punctuation, no spaces) must still terminate."""
    chunks = gn.split_transcript("x" * 50_000, budget=10_000)
    assert sum(len(c) for c in chunks) >= 50_000
    assert all(len(c) <= 10_000 for c in chunks)


def _stub_sources(monkeypatch, transcript: str) -> None:
    monkeypatch.setattr(gn, "_sources",
                        lambda mdir: ("City Council Meeting", "May 14, 2026",
                                      "AGENDA TEXT", "ATTACHMENTS", transcript))


def test_notes_for_uses_single_pass_when_sources_fit(monkeypatch) -> None:
    _stub_sources(monkeypatch, "A short meeting. It adjourned.")
    calls = []

    def call(prompt: str, expect: str) -> str:
        calls.append((prompt, expect))
        return "# Meeting Notes - single"

    assert gn.notes_for(Path("."), call=call) == "# Meeting Notes - single"
    assert len(calls) == 1                        # no map-reduce
    assert "A short meeting." in calls[0][0]      # whole transcript in one call


def test_notes_for_chunks_and_merges_when_too_large(monkeypatch) -> None:
    _stub_sources(monkeypatch, _fake_transcript(12_000))
    calls = []

    def call(prompt: str, expect: str) -> str:
        calls.append((prompt, expect))
        return ("# Meeting Notes - merged" if expect == "# Meeting Notes"
                else "## Session facts\n\n(none in this portion)")

    assert gn.notes_for(Path("."), call=call) == "# Meeting Notes - merged"
    assert len(calls) > 2                              # several extracts, then a merge
    assert all(e == "## " for _, e in calls[:-1])      # map passes expect a section
    assert calls[-1][1] == "# Meeting Notes"           # reduce pass expects the doc
    assert "### Part 1 of" in calls[-1][0]             # extracts reach the merge
    assert all(len(p) <= gn.PROMPT_CHAR_BUDGET for p, _ in calls)


def test_unsupported_figures_flags_a_fabricated_amount() -> None:
    sources = "Architectural Services with Nola|VanPeursem Architects, P.C."
    notes = "the architectural services contract for $1,334,500."
    assert gn.unsupported_figures(notes, sources) == ["$1,334,500"]


def test_unsupported_figures_accepts_verbatim_amounts() -> None:
    sources = "Total Cost: $175,000.00 and a grand total of $53,617,414.27"
    notes = "a $175,000.00 contract against $53,617,414.27 in expenditures"
    assert gn.unsupported_figures(notes, sources) == []


def test_unsupported_figures_ignores_comma_and_space_differences() -> None:
    assert gn.unsupported_figures("costs $1,012,230.91", "$ 1012230.91 paid") == []


def test_unsupported_figures_reports_restated_amounts() -> None:
    """"12 million" rewritten as "$12,000,000" is not fabricated, but is worth a look."""
    assert gn.unsupported_figures("$12,000,000 total", "about 12 million dollars") == ["$12,000,000"]


def test_notes_for_flags_unsupported_figures(monkeypatch, capsys) -> None:
    _stub_sources(monkeypatch, "A short meeting. It adjourned.")
    gn.notes_for(Path("."), call=lambda p, e: "# Meeting Notes - it cost $999,999.")
    assert "$999,999" in capsys.readouterr().err
