# Project notes

Cross-session state for this repo. (This is a personal project — notes live
here, not in caden-work-machine.)

## Key technical facts (hard-won, undocumented APIs)

- Videos are on **Castus TV VOD** (`cloud.castus.tv/vod/hsv-tv/embed/<id>`), iframe on each
  `huntsvilleal.gov/videos/<slug>/` page.
- MP4 resolve: `POST https://imd0mxanj2.execute-api.us-west-2.amazonaws.com/upload/get`
  body `{"file": "<id>", "type": "vod", "user": ""}` → unsigned CloudFront URL (~1.6 GB, 1080p only).
- Captions: `POST .../upload/get-captions` body `{"file": {"_id": "<id>"}, "user": {"_id": ""}}`
  → signed S3 URL for WebVTT. **Only recent videos have VTTs** (the three June 2026 meetings
  yes, April/May 404) — Whisper is the only transcript source for older meetings.
- Meeting list: scrape `huntsvilleal.gov/videocategory/city-council-meetings/` (+ `page/N/`);
  WP REST API for the `videos` post type is disabled.
- Agendas: Legistar Web API `webapi.legistar.com/v1/huntsvilleal/events` (OData filters work).

## Next up

- [ ] Transcribe the new **2026-07-09** meeting: run Whisper locally (M2 Max) to produce its
      transcript, then `/council-notes`. CI only discovers + publishes audio; `has_whisper`
      is still false. (The Friday Action added the agenda, meeting.json, and audio release asset.)
- [ ] Run `/council-notes` on the remaining meetings without notes (Apr 9, Apr 23, May 14,
      Jun 1; May 28 has an uncommitted pre-command draft — regenerate or reshape it)

## Recently done

- (2026-07-10) **First scheduled Friday Action verified clean.** Run
  [29103885416](https://github.com/Caden-Helbling/hsv-city-council-transcripts/actions/runs/29103885416)
  (schedule, 48m) discovered the new **2026-07-09** meeting (agenda + meeting.json → commit
  `e41c470`), published its audio opus release asset (tag `audio-2026-07-09-city-council-meeting`),
  and recorded the manifest audio flag (commit `7b1f6ff`) — `git pull --rebase` + push landed
  with no race. `extract-votes` ran and skipped all 8 meetings (still no Final minutes — Legistar
  shows Draft/Unapproved). Confirms the push-race fix from the first dispatch.

- (2026-07-07) Added `extract-votes [slugs...]` subcommand: parses a meeting's minutes into
  `meetings/<slug>/votes.json` (every Res/Ord number in minutes order, each with its
  roll-call or `null`), re-checks Legistar for late-published minutes, and adds a
  `has_votes` status flag. Verified end-to-end against the 2025-12-18 Final minutes
  (45 items, 40 roll-calls). Ran against all 7 repo meetings — **all skipped**: Huntsville
  has published no Final minutes PDF for any 2026 meeting yet (Jan–Apr are "Unapproved
  Minutes", May–Jun "Draft"; `EventMinutesFile` null on all). Re-run once minutes go Final.

- (2026-07-07) Added `votes <res-no>` subcommand (`scripts/hsvcc.py`) + `tests/test_votes.py`:
  resolves a Resolution/Ordinance number → Legistar matter → roll-call from the Final
  minutes PDF, detecting Consent-Agenda sweeps vs individual roll-calls. Used it to build
  the Flock voting record in the `flock-talk` repo (all 5 Flock authorizations passed
  unanimously; 4 of 5 rode the consent agenda). Note: MatterEnactmentNumber is null in
  this Legistar instance — the adopted "23-689" number lives in MatterTitle text, and
  per-person Aye/Nay names exist ONLY in the minutes PDF, not the API.

- (2026-07-06) Added `/council-notes` project command (`.claude/commands/`, now tracked in
  git); validated on June 11. June 11 transcript names Caden re: the Flock ALPR records
  request — see that meeting's notes.

- (2026-07-03) Designed + implemented full pipeline, backfilled since April, pushed to GitHub.
- (2026-07-03) Full backfill complete: 7 meetings, all with agendas + Whisper-medium transcripts;
  3 June meetings also have official captions; audio opus published as release assets by CI.
  Whisper medium/MPS ran ~40x realtime on the M2 Max — full backlog in ~25 min, not hours.
