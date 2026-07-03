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
├── minutes.pdf         # when published
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
```

`fetch-audio --publish` is the CI mode: extracts audio and uploads it as a
GitHub release asset tagged `audio-<slug>` instead of keeping it locally.

## Automation

`.github/workflows/sync.yml` runs Friday mornings (meetings are Thursday
evenings) and on manual dispatch:

1. `discover` — commits new manifests, agendas, captions.
2. `fetch-audio --all-pending --publish` — extracts each new meeting's
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
