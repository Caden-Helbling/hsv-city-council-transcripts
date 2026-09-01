#!/usr/bin/env python3
"""Draft meeting notes with the local LLM — a reviewed step, not a scheduled one.

Builds the /council-notes-style input for one meeting — FULL agenda text
(pdftotext of agenda.pdf, so the officials cover block is available for name
normalization), trimmed attachment excerpts (canonical for dollar amounts and
recipient names), and the Whisper transcript (captions.txt as fallback) —
then asks the local model (same endpoint/env config as summarize_agendas) to
write notes.md following the output contract in prompts/meeting-notes.md.

The output is a DRAFT: local-model notes are good but can still misattribute
votes or mangle a name the sources don't pin down. Review before committing —
this script deliberately refuses to overwrite an existing notes.md without
--force.

Usage: python scripts/generate_notes.py <slug-or-date-substring> [--force]
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grounding  # noqa: E402
from hsvcc import Manifest, _pdf_text  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
MEETINGS_DIR = REPO_ROOT / "meetings"
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "meeting-notes.md"

BASE_URL = os.environ.get("SUMMARY_BASE_URL", "https://slayden-api.duckdns.org")
MODEL = os.environ.get("SUMMARY_MODEL", "qwen3.5-35b")
TIMEOUT = 1800
ATTACHMENT_SECTION_CAP = 2_000   # notes need names, not full line-item tables
PROMPT_CHAR_BUDGET = 220_000     # ~62K tokens — keep under the 64K server ctx
CHUNK_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "meeting-notes-chunk.md"
MERGE_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "meeting-notes-merge.md"
CHUNK_OVERLAP = 1_500            # carry-over so an item split at a seam has context
MIN_CHUNK_CHARS = 20_000         # below this the agenda alone is crowding out speech


def trim_attachments(attachments_md: str, cap: int = ATTACHMENT_SECTION_CAP) -> str:
    """Cap each '## <name>' section — enough for recipients/totals, not tables."""
    parts = re.split(r"(?m)^(## .+)$", attachments_md)
    out = [parts[0]]
    for heading, body in zip(parts[1::2], parts[2::2]):
        body = body.strip()
        if len(body) > cap:
            body = body[:cap] + "\n[... truncated ...]"
        out.append(f"{heading}\n\n{body}\n")
    return "\n".join(out)


# The figure check lives in grounding.py, shared with the agenda summarizer.
# Re-exported so callers and tests can reach it from either module.
unsupported_figures = grounding.unsupported_figures


def _sources(mdir: Path) -> tuple[str, str, str, str, str]:
    """(title, date_long, agenda_text, attachment_excerpts, transcript)."""
    manifest = Manifest.load(mdir)
    agenda = _pdf_text(mdir / "agenda.pdf") if (mdir / "agenda.pdf").exists() else None
    if not agenda:
        raise RuntimeError("no readable agenda.pdf - the agenda is required "
                           "for name/number normalization")
    transcript_f = mdir / "transcript" / "whisper-medium.txt"
    if transcript_f.exists():
        transcript = transcript_f.read_text(encoding="utf-8")
    elif (mdir / "captions.txt").exists():
        transcript = (mdir / "captions.txt").read_text(encoding="utf-8")
        print("note: no whisper transcript; using captions.txt")
    else:
        raise RuntimeError("no transcript (whisper or captions) - run "
                           "scripts/transcribe-council.ps1 or hsvcc.py transcribe first")
    att_f = mdir / "agenda-attachments.md"
    attachments = trim_attachments(att_f.read_text(encoding="utf-8")) if att_f.exists() \
        else "(none provided)"
    from datetime import date
    d = date.fromisoformat(manifest.date)
    return (manifest.body or manifest.title,
            f"{d.strftime('%B')} {d.day}, {d.year}",
            agenda.strip(), attachments, transcript.strip())


def _fill(template: str, **fields: str) -> str:
    for k, v in fields.items():
        template = template.replace("{" + k + "}", v)
    return template


_SENT_END = re.compile(r"[.!?]\s")


def _cut_point(text: str, lo: int, hi: int) -> int:
    """Best split index in [lo, hi): last sentence end, else last space, else hi."""
    window = text[lo:hi]
    ends = [m.end() for m in _SENT_END.finditer(window)]
    if ends:
        return lo + ends[-1]
    space = window.rfind(" ")
    return lo + space + 1 if space > 0 else hi


def split_transcript(transcript: str, budget: int,
                     overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split a transcript into <=budget-char pieces on sentence boundaries.

    Whisper output is one unbroken line - hundreds of thousands of characters
    with no newline to split on - so the cut has to be found in the prose. Each
    piece after the first repeats the tail of the one before it, so an item
    straddling a seam is visible whole to at least one pass.
    """
    if budget <= 0:
        raise ValueError(f"chunk budget must be positive, got {budget}")
    text = transcript.strip()
    if len(text) <= budget:
        return [text]
    overlap = max(0, min(overlap, budget // 4))
    # Fill to `budget` and the last chunk is a stub - 179K then 33K on the
    # May 14 transcript. Spread the text evenly over the same number of calls
    # instead, so every part gets comparable room.
    step = budget - overlap
    parts = -(-(len(text) - overlap) // step)
    target = min(budget, -(-(len(text) + (parts - 1) * overlap) // parts))
    spans: list[tuple[int, int]] = []
    start = 0
    while start < len(text):
        end = start + target
        if end >= len(text):
            spans.append((start, len(text)))
            break
        cut = _cut_point(text, start + (target * 3) // 4, end)
        spans.append((start, cut))
        nxt = cut - overlap
        start = nxt if nxt > start else cut
    # Backing up to a sentence boundary loses a few characters per cut, which
    # can leave a stub span at the end - an extra model call for a sentence or
    # two. Fold it into its predecessor when that still fits.
    if len(spans) > 1:
        head, _ = spans[-2]
        tail_end = spans[-1][1]
        stub = spans[-1][1] - spans[-1][0] < target // 2
        if stub and tail_end - head <= budget:
            spans[-2] = (head, tail_end)
            spans.pop()
    return [text[a:b] for a, b in spans]


def build_prompt(mdir: Path) -> str:
    """The single-pass prompt. Raises if the meeting is too large for one call."""
    title, date_long, agenda, attachments, transcript = _sources(mdir)
    prompt = _fill(PROMPT_PATH.read_text(encoding="utf-8"),
                   title=title, date_long=date_long, agenda=agenda,
                   attachments=attachments, transcript=transcript)
    if len(prompt) > PROMPT_CHAR_BUDGET:
        raise RuntimeError(f"prompt too large for the local context window "
                           f"({len(prompt)} chars > {PROMPT_CHAR_BUDGET})")
    return prompt


def generate(prompt: str, expect: str = "# Meeting Notes") -> str:
    resp = requests.post(
        f"{BASE_URL}/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['SLAYDEN_API_TOKEN']}"},
        json={
            "model": MODEL,
            "max_tokens": 8192,
            "messages": [{"role": "user", "content": prompt}],
            "chat_template_kwargs": {"enable_thinking": False},
        },
        timeout=TIMEOUT)
    resp.raise_for_status()
    choice = resp.json()["choices"][0]
    if choice.get("finish_reason") != "stop":
        raise RuntimeError(f"generation did not finish: {choice.get('finish_reason')}")
    text = (choice["message"].get("content") or "").strip()
    if not text.startswith(expect):
        raise RuntimeError(f"unexpected notes shape: {text[:120]!r}")
    return text


def _checked(notes: str, agenda: str, attachments: str, transcript: str) -> str:
    """Pass the draft through, printing what the sources do not back.

    Names are not checked here - see grounding.report.

    Read the output as "check these", never as "these are wrong". On the first
    real run of this path (2026-08-27) all three flagged figures were genuine:
    the transcript stated them as speech - "one point one two six million
    dollars", "forty five thousand ninety dollars" - and writing them as digits
    was correct. grounding.spoken_numbers now understands those forms, but the
    lesson generalises past the fix: a flag is a place to look, and the sources
    decide.
    """
    flagged = grounding.report(notes, f"{agenda}\n{attachments}\n{transcript}",
                               check_names=False)
    if flagged:
        print(f"warn: {len(flagged)} item(s) the sources do not back - "
              f"verify before committing:", file=sys.stderr)
        for line in flagged:
            print(f"  {line}", file=sys.stderr)
    return notes


def notes_for(mdir: Path, call: "callable[..., str]" = generate) -> str:
    """Meeting notes: one pass when the sources fit, map-reduce when they do not.

    Two of the twelve meetings on file overflow the 64K context on the
    transcript alone, so those are extracted portion by portion and merged in a
    second pass. Meetings that fit keep the single-pass path unchanged - one
    call that reads the whole transcript is still the better draft.
    """
    title, date_long, agenda, attachments, transcript = _sources(mdir)
    single = _fill(PROMPT_PATH.read_text(encoding="utf-8"),
                   title=title, date_long=date_long, agenda=agenda,
                   attachments=attachments, transcript=transcript)
    if len(single) <= PROMPT_CHAR_BUDGET:
        return _checked(call(single, "# Meeting Notes"), agenda, attachments, transcript)

    chunk_tpl = CHUNK_PROMPT_PATH.read_text(encoding="utf-8")
    fixed = _fill(chunk_tpl, title=title, date_long=date_long, agenda=agenda,
                  attachments=attachments, part="99", total="99", chunk="")
    budget = PROMPT_CHAR_BUDGET - len(fixed)
    if budget < MIN_CHUNK_CHARS:
        raise RuntimeError(f"agenda and attachments leave only {budget} chars "
                           f"for the transcript; trim the attachment excerpts")
    chunks = split_transcript(transcript, budget)
    print(f"transcript is {len(transcript):,} chars; extracting in "
          f"{len(chunks)} parts of up to {budget:,}")
    extracts = []
    for i, chunk in enumerate(chunks, 1):
        print(f"  part {i}/{len(chunks)} ({len(chunk):,} chars)...")
        out = call(_fill(chunk_tpl, title=title, date_long=date_long,
                         agenda=agenda, attachments=attachments,
                         part=str(i), total=str(len(chunks)), chunk=chunk), "## ")
        extracts.append(f"### Part {i} of {len(chunks)}\n\n{out}")

    merge = _fill(MERGE_PROMPT_PATH.read_text(encoding="utf-8"),
                  title=title, date_long=date_long, agenda=agenda,
                  attachments=attachments, extracts="\n\n".join(extracts))
    if len(merge) > PROMPT_CHAR_BUDGET:
        raise RuntimeError(f"merge prompt too large ({len(merge)} chars > "
                           f"{PROMPT_CHAR_BUDGET}) from {len(chunks)} extracts")
    print(f"  merging {len(chunks)} extracts ({len(merge):,} chars)...")
    return _checked(call(merge, "# Meeting Notes"), agenda, attachments, transcript)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meeting", help="slug or date substring, e.g. 2026-08-13")
    parser.add_argument("--force", action="store_true",
                        help="overwrite an existing notes.md")
    args = parser.parse_args(argv)
    if not os.environ.get("SLAYDEN_API_TOKEN"):
        print("SLAYDEN_API_TOKEN not set", file=sys.stderr)
        return 1
    matches = [d for d in sorted(MEETINGS_DIR.iterdir())
               if d.is_dir() and args.meeting in d.name]
    if len(matches) != 1:
        print(f"expected exactly one meeting matching {args.meeting!r}, "
              f"found {[d.name for d in matches]}", file=sys.stderr)
        return 1
    mdir = matches[0]
    if (mdir / "notes.md").exists() and not args.force:
        print(f"{mdir.name}/notes.md already exists (use --force)", file=sys.stderr)
        return 1
    notes = notes_for(mdir)
    (mdir / "notes.md").write_text(notes + "\n", encoding="utf-8")
    print(f"wrote {mdir / 'notes.md'}")
    print("DRAFT — review against the transcript before committing "
          "(votes, names, numbers).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
