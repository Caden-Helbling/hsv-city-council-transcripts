---
description: Generate structured notes.md for a council meeting folder from its transcript + agenda
argument-hint: <meeting date or slug substring>
---

Generate `notes.md` for the meeting matching `$ARGUMENTS` (a date like "june 11" /
"2026-06-11" or any slug substring, matched against `meetings/*/`). If no argument
is given, list meetings that lack a `notes.md` and ask which to run. If the match
is ambiguous, ask.

## Sources (read all that exist in the meeting folder)

1. `transcript/whisper-medium.txt` — primary record of what was said.
2. `agenda.pdf` — canonical for item numbers, resolution/ordinance numbers, proper
   nouns, sponsors, term dates. Whisper garbles names; every name, number, and date
   in the notes must be normalized against the agenda.
3. `captions.txt` — secondary check when present.
4. `meeting.json` — meeting metadata.

## Output contract

Write `meetings/<slug>/notes.md` with exactly these parts, in this order, matching
the exemplar `meetings/2026-06-25-city-council-meeting/notes.md`:

1. **Title:** `# Meeting Notes — Huntsville City Council <type>, <Month D, YYYY>`
2. **Header block:** called to order / adjourned times, presiding officer, members
   present, key officials present, and a `**Sources:**` line naming the files used
   with the note that names/numbers are normalized against the agenda.
3. **`## TL;DR`** — 3–7 bullets: outcomes a resident would care about most
   (what passed/failed/postponed/withdrawn, money, land use, controversy).
4. **`## Decisions`** — one table covering EVERY item acted on: `| Item | Subject |
   Outcome |`. Include resolution/ordinance numbers, appointee names and term end
   dates, dollar amounts, vote splits, abstentions, and postponement target dates.
   Items introduced without action get a one-line list after the table.
5. **`## Discussion highlights`** — bold-led paragraphs for the handful of items
   with real deliberation: who said what, concrete numbers, explicit asks made of
   the council, and staff commitments.
6. **`## Public comments`** — numbered list, one entry per speaker: name and the
   substance of their ask or complaint.
7. **`## Watch list / follow-ups`** — dated returns (postponed items, hearings
   set), unanswered asks, and anything a future meeting should be checked against.

Uncertainty is flagged inline where it occurs — e.g. *(attribution uncertain in
transcript)*, *(verify in minutes)* — never in a separate caveats section. If the
transcript never records a vote the agenda expects, say so in that item's table row.

## After writing

Commit as `docs: add meeting notes for <Month D> council meeting`, push, and send
the file to the user with SendUserFile.
