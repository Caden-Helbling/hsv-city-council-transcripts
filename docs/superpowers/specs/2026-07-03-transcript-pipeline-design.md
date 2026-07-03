# Huntsville City Council Transcript Pipeline — Design

**Date:** 2026-07-03
**Status:** Approved (user answered all scoping questions; final section-level sign-off pending)
**Repo:** `hsv-city-council-transcripts` (private)

## Purpose

A reusable, LLM-free pipeline that collects Huntsville City Council meeting
videos, agendas, and transcripts into per-meeting folders, so that any LLM
service (Claude or otherwise) can later be pointed at the plain-text artifacts
to generate notes. Backfills to April 2026 and keeps up with new meetings.

## Source-system findings (verified 2026-07-03)

1. **Videos** are hosted on Castus TV VOD. Each city video page
   (`huntsvilleal.gov/videos/<slug>/`) embeds an iframe:
   `https://cloud.castus.tv/vod/hsv-tv/embed/<castus_id>`.
2. **MP4 resolution:** unauthenticated
   `POST https://imd0mxanj2.execute-api.us-west-2.amazonaws.com/upload/get`
   with body `{"file": "<castus_id>", "type": "vod", "user": ""}` returns a
   direct, unsigned CloudFront MP4 URL
   (`https://dlttx48mxf9m3.cloudfront.net/outputs/<id>/Default/MP4/out_1080.mp4`,
   ~1.6 GB per meeting). Only the 1080p rendition exists; no HLS, no
   lower-res variants.
3. **Official captions:** `POST .../upload/get-captions` with body
   `{"file": {"_id": "<castus_id>"}, "user": {"_id": ""}}` returns a
   short-lived signed S3 URL for a WebVTT file (~114 KB). Caption quality is
   good (punctuated, clean sentences). Captions exist for all city videos.
4. **Meeting enumeration:** WP REST API for the `videos` post type is
   disabled (returns `[]`). Scraping the category archive
   `huntsvilleal.gov/videocategory/city-council-meetings/` (paginated,
   `page/2/` etc.) yields video-page links; 275 videos in the category.
5. **Agendas/minutes:** Legistar Web API
   `https://webapi.legistar.com/v1/huntsvilleal/events?$orderby=EventDate desc`
   returns JSON events with `EventAgendaFile` (direct PDF URL),
   `EventMinutesFile`, `EventBodyName` (e.g. "City Council Regular Meeting",
   "City Council Work Session"), `EventDate`, `EventId`, `EventInSiteURL`.

## Decisions (user-confirmed)

| Decision | Choice |
| --- | --- |
| Transcript sources | Both: fetch official Castus VTT **and** run Whisper locally |
| Meeting scope | Everything in the "City Council Meetings" video category (regular, work, special/joint sessions) |
| Media retention | Keep extracted audio (gitignored/release assets); delete MP4s after extraction |
| Automation split | Hybrid: GH Action does discovery + agendas + VTTs + audio extraction; Whisper runs locally on the M2 Max |
| Audio distribution | Direct MP4 URL recorded in each manifest **and** CI-extracted opus uploaded as GitHub Release assets |
| Backfill horizon | April 2026 onward |

## Repository layout

```
hsv-city-council-transcripts/
├── README.md
├── requirements.txt              # requests; whisper deps listed as optional extras
├── .gitignore                    # audio/, *.mp4, CLAUDE.md, .claude/, status.md
├── scripts/
│   └── hsvcc.py                  # single typed CLI (discover / fetch-audio / transcribe)
├── .github/workflows/sync.yml    # cron + manual dispatch
├── docs/superpowers/specs/       # this document
├── meetings/
│   └── <YYYY-MM-DD>-<slug>/
│       ├── meeting.json          # manifest — contract between CI and local runs
│       ├── agenda.pdf
│       ├── minutes.pdf           # when published
│       ├── captions.vtt          # official Castus captions
│       ├── captions.txt          # plain-text render of the VTT
│       └── transcript/
│           ├── whisper-medium.txt
│           └── whisper-medium.srt
└── audio/                        # gitignored local scratch for .opus files
```

## Manifest schema (`meeting.json`)

```json
{
  "slug": "2026-06-25-city-council-regular-meeting",
  "title": "Huntsville City Council Meeting – June 25, 2026",
  "date": "2026-06-25",
  "body": "City Council Regular Meeting",
  "video_page_url": "https://www.huntsvilleal.gov/videos/...",
  "castus_id": "6a3dcff79537260002c64cd9",
  "mp4_url": "https://dlttx48mxf9m3.cloudfront.net/outputs/.../out_1080.mp4",
  "legistar_event_id": 1223,
  "legistar_url": "https://huntsvilleal.legistar.com/MeetingDetail.aspx?...",
  "agenda_url": "https://huntsvilleal.legistar1.com/.../Agenda.pdf",
  "minutes_url": null,
  "audio_asset_tag": "audio-2026-06-25-city-council-regular-meeting",
  "status": {
    "has_agenda": true,
    "has_minutes": false,
    "has_captions": true,
    "has_audio_asset": true,
    "has_whisper": false
  }
}
```

`status` flags are recomputed by `discover` from what is actually on disk /
in releases, so re-runs self-heal.

## CLI (`scripts/hsvcc.py`)

Python 3.10+, fully type-hinted, `requests` as the only required dependency.
Whisper (`openai-whisper`, torch) is required only for `transcribe`.

- **`discover [--since YYYY-MM-DD]`** (default `--since 2026-04-01`)
  1. Scrape the category archive pages for video links; stop paginating when
     all parsed dates on a page predate `--since`.
  2. Parse each video page: title, meeting date (from the title), Castus
     embed ID from the iframe.
  3. Resolve the MP4 URL via the Castus `upload/get` API.
  4. Fetch the caption VTT via `upload/get-captions` (signed URL is
     short-lived; download immediately). Render `captions.txt`
     (dedup + strip cue timing; keep a `[HH:MM:SS]` marker every ~5 min).
  5. Pull Legistar events in the date window; match video→event by date.
     Multiple events on one date are disambiguated by body-name keywords
     from the video title ("work session" → Work Session, etc.). No match →
     warn, leave `legistar_event_id: null`.
  6. Download agenda/minutes PDFs when present.
  7. Write/refresh manifests. Idempotent: existing files are not
     re-downloaded unless missing; late-published minutes/captions get
     picked up on later runs.
- **`fetch-audio <slug ... | --all-pending>`**
  Prefer `gh release download <audio_asset_tag>`; fall back to downloading
  `mp4_url` and extracting audio locally (`ffmpeg -i in.mp4 -vn -ac 1 -ar
  16000 -c:a libopus -b:a 24k audio/<slug>.opus`), then delete the MP4.
- **`transcribe <slug ... | --all-pending>`**
  Whisper medium, MPS, fp32 (mirrors the existing `whisper_processor.py`
  config) on `audio/<slug>.opus` → `transcript/whisper-medium.{txt,srt}`;
  set `status.has_whisper`. Serialize runs (MPS does not parallelize).

## GitHub Action (`sync.yml`)

- **Triggers:** cron Friday 13:00 UTC (meetings are Thursday evenings) +
  `workflow_dispatch`.
- **Steps:**
  1. Checkout; install Python + `requests` + ffmpeg (apt).
  2. `hsvcc.py discover` → commit any new/changed manifests, agendas,
     VTTs, captions.txt (`git diff --quiet || commit+push`).
  3. For each manifest with `has_audio_asset: false`: stream-download the
     MP4, extract opus, create release `audio-<slug>` with the opus attached
     (`gh release create`), delete local MP4, update manifest flag, commit.
  4. Job-level guard: single concurrent run (`concurrency` group), so cron
     and manual dispatch never race.
- No LLM calls anywhere. Uses the default `GITHUB_TOKEN` (contents: write).
- Disk: runners have ~14 GB free — process one meeting at a time,
  delete each MP4 before the next.

## Error handling

- Every per-meeting network step is wrapped: failures log a warning with the
  slug and continue with the next meeting; exit code is non-zero if any
  meeting failed (so the Action surfaces partial failures) but completed work
  is still committed.
- Castus/Legistar API response shapes are asserted with clear messages —
  they are undocumented and may drift; a shape change should fail loudly,
  not silently write garbage.
- Missing Legistar match (joint/special sessions) is a warning, not an
  error; the meeting folder still gets video/captions.

## Testing

`pytest` with recorded fixtures (no live network in tests):
- archive-page HTML → expected video links/dates
- video-page HTML → Castus ID extraction
- Castus `upload/get` / `get-captions` JSON → URL extraction
- Legistar events JSON → matching logic (incl. two-events-same-day and
  no-match cases)
- VTT → captions.txt rendering (dedup, timestamps)
- manifest read/write round-trip + status recomputation

## Out of scope (deliberate)

- Note generation / any LLM integration — the pipeline only produces
  plain-text artifacts an LLM can consume later. A `/council-notes`-style
  slash command can be layered on separately.
- Meetings before April 2026 (the pipeline supports them via `--since`, we
  just don't backfill them now).
- Other video categories (planning commission, etc.) — the category slug is
  a constant that could later become a flag.
