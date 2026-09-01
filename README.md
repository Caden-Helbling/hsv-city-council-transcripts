# hsv-city-council-transcripts

LLM-free pipeline that archives Huntsville (AL) City Council meetings:
video → audio → transcripts, paired with the official Legistar agenda for
each meeting. Any LLM service can then be pointed at a meeting folder to
generate notes — the pipeline itself makes zero LLM calls.

## How it works

| Source | What we take |
| --- | --- |
| `huntsvilleal.gov/videocategory/city-council-meetings/` | Meeting list (regular, work, special/joint sessions) |
| Castus TV VOD (`cloud.castus.tv/vod/hsv-tv`) | Direct MP4 URL + official closed-caption VTT |
| Legistar Web API (`webapi.legistar.com/v1/huntsvilleal`) | Agenda PDF, minutes PDF, meeting metadata |
| OpenAI Whisper (local, medium model, MPS) | Higher-fidelity transcript |

Each meeting gets a folder:

```
meetings/2026-06-25-city-council-meeting/
├── meeting.json        # manifest: dates, URLs, IDs, status flags
├── agenda.pdf          # from Legistar
├── agenda-preview.md   # pre-meeting topic summary (from the Tuesday preview run)
├── minutes.pdf         # when published
├── votes.json          # per-item roll-calls parsed from minutes (extract-votes)
├── captions.vtt        # official captions
├── captions.txt        # plain-text captions with [HH:MM:SS] markers
└── transcript/
    ├── whisper-medium.txt
    └── whisper-medium.srt
```

## CLI

```bash
pip install -r requirements.txt          # just `requests`

# find meetings, fetch agendas + captions (idempotent, safe to re-run)
python3 scripts/hsvcc.py discover --since 2026-04-01

# get audio: prefers the CI-published release asset, falls back to
# downloading the ~1.6 GB MP4 and extracting 16 kHz mono opus via ffmpeg
python3 scripts/hsvcc.py fetch-audio --all-pending

# local Whisper transcription (needs: pip install openai-whisper)
python3 scripts/hsvcc.py transcribe --all-pending

# look up how the Council voted on a Resolution/Ordinance number
python3 scripts/hsvcc.py votes 23-689

# parse every item's roll-call out of each meeting's minutes -> votes.json
python3 scripts/hsvcc.py extract-votes                # all meetings (default)
python3 scripts/hsvcc.py extract-votes <slug> ...     # specific meetings

# before a meeting happens: grab its agenda from Legistar, summarize the
# topics, and check every link inside the PDF -> upcoming/<date>-<body>/
python3 scripts/hsvcc.py preview-agendas              # next 7 days
python3 scripts/hsvcc.py preview-agendas --window 14

# build agenda-preview.md from the archived agenda.pdf for meetings that
# never got one (predates the preview run, or agenda posted late)
python3 scripts/hsvcc.py backfill-previews
```

`votes` resolves the adopted number to its Legistar matter, prints the
action/mover/seconder, then extracts the roll-call from the Final minutes PDF —
distinguishing an **individual roll-call** from a **Consent Agenda** sweep (where
the item passed in a bundle with no separate vote or debate). Minutes text
extraction uses `pdftotext` (poppler) if present, else `pypdf`/`PyPDF2`; without
either it still prints the matter info and the minutes URL. Draft/unpublished
minutes have no roll-call to extract.

`extract-votes` does the same parse for **every** Resolution/Ordinance number
in a meeting's minutes and writes the results to `meetings/<slug>/votes.json`
(items in minutes order; `"vote": null` where no roll-call is recorded). It
re-checks Legistar for late-published minutes, downloads `minutes.pdf` into
the meeting folder, and skips meetings whose minutes are still Draft or
Unapproved — as of 2026-07-07 that is every 2026 meeting. The Friday sync
workflow runs it automatically, so votes.json files appear as Final minutes
land.

`fetch-audio --publish` is the CI mode: extracts audio and uploads it as a
GitHub release asset tagged `audio-<slug>` instead of keeping it locally.

`preview-agendas` works *ahead* of the meeting: `discover` is driven by the
video archive (which only lists meetings after they happen), so previews come
straight from Legistar's events feed instead. Each upcoming meeting with a
published agenda gets `upcoming/<date>-<body>/` holding the agenda PDF, the
raw Legistar event record, and `agenda-preview.md` — a deterministic (no-LLM)
summary of every agenda item grouped by section, plus an HTTP check of every
link embedded in the PDF (Legistar matter pages + attachments). Agendas are
re-downloaded on every run to catch amendments. Once a meeting has passed and
`discover` has created the real `meetings/<slug>/` folder, the preview
markdown is archived there as `agenda-preview.md` and the `upcoming/` entry
is pruned (matched by Legistar event id, with a 14-day grace period).

## Automation

`.github/workflows/sync.yml` runs on two schedules plus manual dispatch
(dispatch runs both jobs, sync first):

**Tuesday evenings** (23:00 UTC / 6 pm CT — ahead of Thursday's meeting),
the `preview` job runs `preview-agendas` and commits `upcoming/` — agenda
PDF, topic summary, and link-check results for each upcoming meeting. It then
runs `scripts/summarize_agendas.py`, the repo's **one LLM step**: a single
call per new/amended agenda that writes `summary.md` (plain-language bullets
for the website's main page — one per agenda item, so a reader sees everything
the council will take up; 40-plus for a full regular meeting). Alongside the preview, the pipeline
also writes `agenda-attachments.md` — deterministic text excerpts of
high-value Legistar attachments (expenditure lists, bid summaries,
improvement-fund appropriations, resolved via the Legistar API from the
agenda's matter links) — so summaries can quote real dollar amounts; the
prompt requires every figure to appear verbatim in the input. It runs on
the self-hosted
Qwen3.5-35B (llama-server on slayden) through its token-authed public
endpoint — `SLAYDEN_API_TOKEN` repo secret; base URL and model overridable
via `SUMMARY_BASE_URL` / `SUMMARY_MODEL`. Qwen must run with thinking
disabled here (`chat_template_kwargs`): thinking mode spends the whole
output budget reasoning and emits nothing. The layer is strictly additive —
no token or an unreachable server skips gracefully, the site falls back to
the verbatim topic list, and a generation failure never fails the sync. The
scraping/parsing pipeline itself remains LLM-free. Summaries regenerate only
when the agenda content actually changes (tracked by a source hash in
`summary.md`). A **backlog check** heals gaps: if the server was down and a
meeting passed without a summary, its archived `meetings/<slug>/agenda-preview.md`
is summarized on the next run where the server is up — both the Tuesday
preview job and the Friday sync job run the check.

**Friday mornings** (meetings are Thursday evenings), the `sync` job runs:

1. `discover` — commits new manifests, agendas, captions.
2. `extract-votes` — once Legistar publishes a meeting's Final minutes,
   commits `minutes.pdf` + `votes.json` for it.
3. `fetch-audio --all-pending --publish` — extracts each new meeting's
   audio (~40 MB opus) and attaches it to a release, so a local
   `fetch-audio` never needs the full video.

Whisper is **not** run in CI (4-core runners are too slow for a 3-hour
meeting at acceptable quality). Instead, `scripts/transcribe-council.ps1`
runs as a **weekly scheduled task on slayden** (Fridays 8 PM, registered via
`powershell -File scripts\transcribe-council.ps1 -Register`): it pulls, checks
for meetings with a published audio asset but no transcript (exits untouched
most weeks), downloads the opus release assets, stops llama-server to free
VRAM, transcribes on the GPU, restarts the LLM stack in a `finally`, and
commits + pushes (which redeploys the site). Log: `D:\llm\logs\transcribe-council.log`.
The log now carries whisper's stderr too: a 2026-08-28 run failed 55s in and
recorded only `WARN: transcribe reported failures`, because the reason went to
stderr while only stdout was piped. cmd.exe does the redirect now (PowerShell 5.1
wraps redirected native stderr in a terminating NativeCommandError) and python
runs `-u`, so progress lines land as they happen.

That task is **Interactive**, so it only fires while caden is signed in;
`StartWhenAvailable` defers a logged-off Friday to the next logon rather than
skipping it, trading a predictable 8 PM window for an unpredictable one.
`scripts\elevated-transcribe-s4u.ps1` (run elevated) converts it to S4U so it
runs logged out. Two things must come with that flip, which is why it is a script
and not a checkbox: llama-server's ACL grants start/stop to `IU` (Interactive
Users, S-1-5-4) and an S4U token is a *batch* logon carrying no S-1-5-4, so the
ACE has to name the account itself; and S4U has no DPAPI master key, so Git
Credential Manager cannot supply the push token and the repo must be on an SSH
remote first. The script refuses to run until origin is SSH, verifies the result
under a real S4U token using a throwaway probe task, and rolls both changes back
if either check fails. `-Revert` undoes it.
`captions.txt` is available immediately either way, when Castus publishes it.

**Meeting notes** (`notes.md`) are drafted with the local LLM too:
`python scripts/generate_notes.py <date>` (same env vars as the summarizer)
feeds the full agenda text, attachment excerpts, and the transcript to the
model with the output contract in `scripts/prompts/meeting-notes.md`. The
result is a **draft** — review names, numbers, and vote records against the
transcript before committing (the script refuses to overwrite an existing
notes.md without `--force`).

Long meetings are handled in two passes. A 3-hour transcript can run past
210,000 characters, which overflows the 64K context on its own, so
`generate_notes.py` splits the transcript on sentence boundaries into
overlapping portions, extracts each one against the agenda
(`prompts/meeting-notes-chunk.md`), then merges the extracts into the same
output contract (`prompts/meeting-notes-merge.md`). Meetings that fit stay on
the single-pass path - one call that reads the whole transcript is the better
draft, so chunking only kicks in when it has to. As of 2026-08-25 that is 2 of
the 12 meetings on file (April 23 and May 14). Either path prints a warning
listing any dollar figure in the draft that appears in none of the sources -
so the figures are worth checking first. Treat a flag as "look here", not as
proof: every figure flagged so far has turned out to be genuine, stated in the
transcript as speech ("forty five thousand ninety dollars") rather than digits.
The checker understands spoken forms now, but the sources always decide.

## Website

The site is live at
**<https://caden-helbling.github.io/hsv-city-council-transcripts/>**. The main
page leads with **upcoming meetings** (from `upcoming/`): a card per meeting
with the plain-language `summary.md` when generated (labeled AI-generated,
falling back to the verbatim topic list), the full parsed agenda in a
collapsible section, and links to the agenda PDF and Legistar. Below that is
the **archive** — one page per past meeting with records links, votes table,
notes, the pre-meeting agenda preview, and the archived plain-language
summary. `scripts/build_site.py` renders everything deterministically from
the repo's data (`pip install -r requirements-site.txt`, then
`python3 scripts/build_site.py` → `_site/`); the `Publish site` workflow
rebuilds and deploys on every push to `main`, so the Tuesday/Friday syncs
republish automatically. Plan doc:
`docs/superpowers/plans/2026-08-13-github-pages-site.md`.

## Generating notes with an LLM

Point your tool of choice at a meeting folder and use:

- `captions.txt` or `transcript/whisper-medium.txt` — what was said
- `agenda.pdf` — what was scheduled (item numbers, ordinances, appropriations)
- `meeting.json` — date, meeting type, Legistar links

## Development

```bash
pip install -r requirements-dev.txt
python3 -m pytest
```

Tests run entirely offline against recorded fixtures in `tests/fixtures/`.
