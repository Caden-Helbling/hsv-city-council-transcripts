#!/usr/bin/env python3
"""Deterministic checks on what the local model wrote, before it is published.

The defect that motivated this is real and reached the public site: the
2026-08-25 agenda summary covered 6 of 85 items, silently dropping the
FBI/schools/police threat-assessment MOU, outside counsel for the fire apparatus
antitrust litigation, and a whole landscape contract re-award. uncovered_items
catches that by string comparison against the agenda - no second model, no
second opinion to trust. An LLM verifier can hallucinate its own approval; a
substring check cannot.

The figure and name checks have not yet caught a fabrication. Four amounts were
flagged during development and every one turned out to be genuine, stated in the
source in a form the check could not see: "one point one two six million
dollars", "forty five thousand ninety dollars", "6752 dollars and 94 cents",
"$12 million". A review acting on those flags would have edited correct numbers
out of accurate notes - which nearly happened. spoken_numbers exists because of
that, and the episode is the reason for the rule below.

These checks are deliberately conservative, and the asymmetry is the whole
design. A miss is tolerable. A false accusation is not: it costs a reader's
trust, and acted on carelessly it corrupts a document that was right.
"""
from __future__ import annotations

import re
from collections import Counter

# ---------------------------------------------------------------- dollar figures

_MONEY = re.compile(r"\$\s?\d[\d,]*(?:\.\d{2})?")


# ------------------------------------------------------- numbers said out loud

# Meeting notes are checked against a Whisper transcript, where people say
# amounts rather than write them: "forty five thousand ninety dollars", "one
# point one two six million". Comparing digit strings to that flags correct
# figures as invented - it flagged all three in the 2026-08-27 draft, all three
# genuine, and the review that followed nearly "corrected" accurate numbers out
# of the notes.
# So spoken forms are converted to digits and added to the haystack.

_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
         "seventy": 70, "eighty": 80, "ninety": 90}
_SCALES = {"hundred": 100, "thousand": 1000, "million": 1000000,
           "billion": 1000000000}
_GLUE = {"and", "point"}

_NUMWORD = re.compile(
    r"\b(?:" + "|".join(list(_ONES) + list(_TENS) + list(_SCALES) + list(_GLUE))
    + r")\b(?:[\s-]+(?:" + "|".join(list(_ONES) + list(_TENS) + list(_SCALES) + list(_GLUE))
    + r")\b)*", re.I)


def _value_of(words: list[str]) -> float | None:
    """Evaluate one run of number words. None when it says no number."""
    if "point" in words:
        i = words.index("point")
        head, tail = words[:i], words[i + 1:]
        scale = 1
        while tail and tail[-1] in _SCALES:
            scale *= _SCALES[tail.pop()]
        if not all(w in _ONES for w in tail) or not tail:
            return None
        whole = _value_of(head) if head else 0
        if whole is None:
            return None
        frac = float("0." + "".join(str(_ONES[w]) for w in tail))
        return (whole + frac) * scale

    total = current = 0
    seen = False
    for w in words:
        if w in _ONES:
            current += _ONES[w]; seen = True
        elif w in _TENS:
            current += _TENS[w]; seen = True
        elif w == "hundred":
            current = (current or 1) * 100; seen = True
        elif w in _SCALES:
            total += (current or 1) * _SCALES[w]; current = 0; seen = True
        # "and" is glue and contributes nothing
    return total + current if seen else None


def spoken_numbers(text: str) -> set[str]:
    """Digit strings for every amount `text` states in words.

    "forty five thousand ninety" -> {"45090"}, and a following "and ninety four
    cents" folds in as {"45090.94"}. Both the whole number and the cents form
    are emitted, since a draft may write either.
    """
    out: set[str] = set()
    low = text.lower()

    # "12 million" - a digit with a spoken scale, which the word scanner below
    # cannot see because the leading token is not a number word.
    for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s+(hundred|thousand|million|billion)\b", low):
        try:
            val = float(m.group(1).replace(",", "")) * _SCALES[m.group(2)]
        except ValueError:
            continue
        out.add(str(int(val)) if val == int(val) else str(val))

    # "6752 dollars and 94 cents" - the agenda PDFs write it this way
    for m in re.finditer(r"(\d[\d,]*)\s+dollars?\s+and\s+(\d{1,2})\s+cents?", low):
        out.add("%s.%02d" % (m.group(1).replace(",", ""), int(m.group(2))))

    for m in _NUMWORD.finditer(low):
        words = [w for w in re.split(r"[\s-]+", m.group(0)) if w]
        val = _value_of(words)
        if val is None:
            continue
        if val == int(val):
            out.add(str(int(val)))
        else:
            out.add(("%.10f" % val).rstrip("0").rstrip("."))
        # "<amount> dollars and <n> cents"
        tail = low[m.end():m.end() + 40]
        cents = re.match(r"\s*dollars?\s+and\s+(.{0,30}?)\s+cents?", tail)
        if cents:
            cw = [w for w in re.split(r"[\s-]+", cents.group(1)) if w]
            cv = _value_of(cw)
            if cv is not None and 0 <= cv < 100:
                out.add("%d.%02d" % (int(val), int(cv)))
    return out


def _flat(text: str) -> str:
    return re.sub(r"[,\s]", "", text)


def unsupported_figures(text: str, sources: str) -> list[str]:
    """Dollar figures in `text` that appear nowhere in `sources`.

    Commas and spaces are ignored, so "$8,000" matches a source "$8 000" and the
    "$    13,999,801.48" spacing real expenditure tables use. Amounts the source
    only states in words count as present too - see spoken_numbers - because a
    transcript says "forty five thousand ninety dollars" and writing that as
    $45,090 is correct, not invented.
    """
    flat = _flat(sources) + "|" + "|".join(sorted(spoken_numbers(sources)))
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
