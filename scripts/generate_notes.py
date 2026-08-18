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
from hsvcc import Manifest, _pdf_text  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
MEETINGS_DIR = REPO_ROOT / "meetings"
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "meeting-notes.md"

BASE_URL = os.environ.get("SUMMARY_BASE_URL", "https://slayden-api.duckdns.org")
MODEL = os.environ.get("SUMMARY_MODEL", "qwen3.5-35b")
TIMEOUT = 1800
ATTACHMENT_SECTION_CAP = 2_000   # notes need names, not full line-item tables
PROMPT_CHAR_BUDGET = 220_000     # ~62K tokens — keep under the 64K server ctx


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


def build_prompt(mdir: Path) -> str:
    manifest = Manifest.load(mdir)
    agenda = _pdf_text(mdir / "agenda.pdf") if (mdir / "agenda.pdf").exists() else None
    if not agenda:
        raise RuntimeError("no readable agenda.pdf — the agenda is required "
                           "for name/number normalization")
    transcript_f = mdir / "transcript" / "whisper-medium.txt"
    if transcript_f.exists():
        transcript = transcript_f.read_text(encoding="utf-8")
    elif (mdir / "captions.txt").exists():
        transcript = (mdir / "captions.txt").read_text(encoding="utf-8")
        print("note: no whisper transcript; using captions.txt")
    else:
        raise RuntimeError("no transcript (whisper or captions) — run "
                           "scripts/transcribe-council.ps1 or hsvcc.py transcribe first")
    att_f = mdir / "agenda-attachments.md"
    attachments = trim_attachments(att_f.read_text(encoding="utf-8")) if att_f.exists() \
        else "(none provided)"
    from datetime import date
    d = date.fromisoformat(manifest.date)
    prompt = (PROMPT_PATH.read_text(encoding="utf-8")
              .replace("{title}", manifest.body or manifest.title)
              .replace("{date_long}", f"{d.strftime('%B')} {d.day}, {d.year}")
              .replace("{agenda}", agenda.strip())
              .replace("{attachments}", attachments)
              .replace("{transcript}", transcript.strip()))
    if len(prompt) > PROMPT_CHAR_BUDGET:
        raise RuntimeError(f"prompt too large for the local context window "
                           f"({len(prompt)} chars > {PROMPT_CHAR_BUDGET})")
    return prompt


def generate(prompt: str) -> str:
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
    if not text.startswith("# Meeting Notes"):
        raise RuntimeError(f"unexpected notes shape: {text[:120]!r}")
    return text


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
    notes = generate(build_prompt(mdir))
    (mdir / "notes.md").write_text(notes + "\n", encoding="utf-8")
    print(f"wrote {mdir / 'notes.md'}")
    print("DRAFT — review against the transcript before committing "
          "(votes, names, numbers).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
