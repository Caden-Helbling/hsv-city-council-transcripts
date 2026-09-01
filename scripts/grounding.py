#!/usr/bin/env python3
"""Deterministic checks on what the local model wrote, before it is published.

Two real defects motivated this, both of which reached the public site:

  - 2026-08-25: the agenda summary covered 6 of 85 items, silently dropping the
    FBI/schools/police threat-assessment MOU, outside counsel for the fire
    apparatus antitrust litigation, and a whole landscape contract re-award.
  - 2026-05-14: a meeting-notes draft invented a $1,334,500 architect fee,
    wrapped in an otherwise accurate sentence about a real agenda item.

Both are caught by string comparison against the sources - no second model, no
second opinion to trust. An LLM verifier can hallucinate its own approval; a
substring check cannot. Prompt wording alone did not hold: the map pass that
invented that fee had been told, in the same prompt, that every dollar figure
must appear verbatim.

These are deliberately conservative. A miss is tolerable; a false accusation
that trains the reader to ignore warnings is not.
"""
from __future__ import annotations

import re
from collections import Counter

# ---------------------------------------------------------------- dollar figures

_MONEY = re.compile(r"\$\s?\d[\d,]*(?:\.\d{2})?")


def _flat(text: str) -> str:
    return re.sub(r"[,\s]", "", text)


def unsupported_figures(text: str, sources: str) -> list[str]:
    """Dollar figures in `text` that appear nowhere in `sources`.

    Commas and spaces are ignored, so "$8,000" matches a source "$8 000" and the
    "$    13,999,801.48" spacing real expenditure tables use. A restatement -
    "12 million" written as "$12,000,000" - is still reported: not a fabrication,
    but worth a glance before it goes out.
    """
    flat = _flat(sources)
    return [fig for fig in sorted(set(_MONEY.findall(text)))
            if _flat(fig).lstrip("$") not in flat]


# ------------------------------------------------------------- agenda coverage

# "- 2026-879       Public Hearing on the zoning of 24.67 acres ..."
_ITEM = re.compile(r"^-\s+(\d{4}-\d+)\s+(.*)$", re.M)
_SPONSORS = re.compile(r"\*\(sponsors:.*?\)\*")
_WORD = re.compile(r"[a-z0-9][a-z0-9.'\-]*")

# Words that appear across most agenda items and so distinguish nothing.
_BOILERPLATE = {
    "resolution", "ordinance", "authorizing", "authorize", "consideration",
    "pertaining", "same", "city", "huntsville", "council", "mayor", "meeting",
    "regular", "held", "enter", "into", "agreement", "between", "with", "the",
    "and", "for", "of", "to", "a", "an", "certain", "public", "hearing",
    "consider", "acting", "upon", "matter", "item", "items", "committee",
    "department", "alabama", "county", "board", "place", "term", "year",
    "years", "expire", "current", "seat", "nominated", "introduced", "from",
    "that", "this", "which", "shall", "will", "been", "have", "has", "was",
    "were", "its", "their", "there", "than", "then", "when", "where", "who",
}


def agenda_items(preview_md: str) -> list[tuple[str, str]]:
    """(item id, title) for each numbered item in an agenda-preview.md."""
    out = []
    for m in _ITEM.finditer(preview_md):
        title = _SPONSORS.sub("", m.group(2)).strip()
        out.append((m.group(1), title))
    return out


def _tokens(text: str) -> set[str]:
    """Content words, with trailing punctuation stripped.

    The interior dot has to survive so "24.67" stays one token, but a trailing
    one must not: it made "council." a different token from "council", so
    boilerplate slipped through as distinctive, and an agenda's "Drive." would
    not match a summary's "Drive," - a false report of a missing item.
    """
    out = set()
    for w in _WORD.findall(text.lower()):
        w = w.rstrip(".'-")
        if len(w) > 3 and w not in _BOILERPLATE:
            out.add(w)
    return out


def uncovered_items(summary: str, preview_md: str,
                    max_df: int = 2) -> list[tuple[str, str]]:
    """Agenda items with no distinctive word anywhere in the summary.

    "Distinctive" is measured against the agenda itself: a word carried by at
    most `max_df` items identifies one. Words shared widely - "resolution",
    "landscape" on an agenda with three landscape contracts - identify nothing
    and are ignored, which is why the threshold is on document frequency rather
    than a fixed stopword list.

    An item with no distinctive words at all (a bare "Resolution authorizing
    travel expenses") is skipped rather than reported: it cannot be judged this
    way, and guessing would produce exactly the false positives that make a
    warning worth ignoring.
    """
    items = agenda_items(preview_md)
    tokenized = [(i, t, _tokens(t)) for i, t in items]

    df: Counter[str] = Counter()
    for _, _, toks in tokenized:
        df.update(toks)

    hay = _tokens(summary)
    missed = []
    for item_id, title, toks in tokenized:
        distinctive = {t for t in toks if df[t] <= max_df}
        if not distinctive:
            continue
        if not (distinctive & hay):
            missed.append((item_id, title))
    return missed


# ------------------------------------------------------------ named entities

# Two or more consecutive Capitalized words: company and person names, the kind
# of detail a model invents most confidently. Single capitalized words are not
# checked - too many are ordinary words at the start of a sentence.
_PROPER = re.compile(r"\b([A-Z][a-zA-Z&.'\-]+(?:\s+[A-Z][a-zA-Z&.'\-]+)+)")

# Headings and labels our own prompts ask for. These are not guesses about what
# a model might emit - they are the literal strings in prompts/meeting-notes.md
# and prompts/laymans-summary.md, so matching them is exact, not heuristic.
_TITLE_NOISE = {
    "the council", "the city", "the mayor", "public hearing", "public hearings",
    "city council", "the finance", "the board", "in plain language",
    "the huntsville", "meeting notes", "huntsville city", "general fund",
    "called to order", "presiding officer", "members present",
    "key officials present", "discussion highlights", "public comments",
    "watch list", "watch list / follow-ups", "consolidated batch",
    "meeting called to order", "meeting adjourned", "mayor present",
    "council members present",
}


def _norm_name(s: str) -> str:
    """Lowercase, collapse whitespace, unify apostrophes, drop trailing dots.

    Every one of those was a false positive in testing: "Barry St. NW." (the
    sentence period swept into the match), "City’s SCADA" (a typographic
    apostrophe out of the agenda PDF vs a straight one in the draft).
    """
    s = s.replace("’", "'").replace("‘", "'")
    s = re.sub(r"\s+", " ", s).strip().lower()
    s = s.rstrip(".,;:")
    # "Von Braun Center's" is the same entity as "Von Braun Center"
    if s.endswith("'s"):
        s = s[:-2]
    return s


def unsupported_names(text: str, sources: str) -> list[str]:
    """Multi-word proper names in `text` that appear nowhere in `sources`.

    Case-, whitespace-, apostrophe- and trailing-punctuation-insensitive: a model
    that reflows "Nola|VanPeursem Architects" is not fabricating.

    A name whose words all appear in the sources is NOT reported, even when that
    exact phrasing does not - "Capital Improvements Fund" assembled from a
    "2014 CAPITAL IMPROVEMENTS" fund row is a restatement, not an invention, and
    reporting it is the kind of noise that teaches a reader to skip the warnings.
    What survives is a name carrying a word the sources never use.
    """
    flat = _norm_name(sources)
    flat_words = set(re.findall(r"[a-z0-9'\-]+", flat))
    out = []
    for name in sorted(set(_PROPER.findall(text))):
        norm = _norm_name(name)
        if norm in _TITLE_NOISE or len(norm) < 8:
            continue
        if norm in flat:
            continue
        words = re.findall(r"[a-z0-9'\-]+", norm)
        if all(w in flat_words for w in words):
            continue
        out.append(name.rstrip(".,;:"))
    return out


# ------------------------------------------------------------------ reporting

def report(text: str, sources: str, preview_md: str | None = None,
           check_names: bool = True) -> list[str]:
    """Human-readable warning lines; empty when everything checks out.

    check_names is off for meeting notes. Notes are tables and bold-led
    paragraphs, and the model labels rows with invented Title Case phrases -
    "Motion Carried", "Consolidated Approval", "See Transcript" - so multi-word
    capitalization stops being an entity signal there and the check produces
    almost nothing but noise. On agenda summaries, which are plain bullets, it
    ran clean across every draft tested.
    """
    lines = []
    for fig in unsupported_figures(text, sources):
        lines.append(f"figure not in sources: {fig}")
    if check_names:
        for name in unsupported_names(text, sources):
            lines.append(f"name not in sources: {name}")
    if preview_md is not None:
        for item_id, title in uncovered_items(text, preview_md):
            short = title if len(title) <= 90 else title[:87] + "..."
            lines.append(f"agenda item not covered: {item_id} {short}")
    return lines
