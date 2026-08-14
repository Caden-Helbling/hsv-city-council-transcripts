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
PDF, topic summary, and link-check results for each upcoming meeting.

**Friday mornings** (meetings are Thursday evenings), the `sync` job runs:

1. `discover` — commits new manifests, agendas, captions.
2. `extract-votes` — once Legistar publishes a meeting's Final minutes,
   commits `minutes.pdf` + `votes.json` for it.
3. `fetch-audio --all-pending --publish` — extracts each new meeting's
   audio (~40 MB opus) and attaches it to a release, so a local
   `fetch-audio` never needs the full video.

Whisper is **not** run in CI (4-core runners are too slow for a 3-hour
meeting at acceptable quality) — run `transcribe` locally when you want the
higher-fidelity transcript. `captions.txt` is available immediately either way.

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
