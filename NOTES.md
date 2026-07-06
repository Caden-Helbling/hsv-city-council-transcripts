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

- [ ] Verify first scheduled Action run (Friday) commits cleanly (first dispatch hit a push race,
      fixed with `git pull --rebase` in sync.yml — unverified until next run)
- [ ] Run `/council-notes` on the remaining meetings without notes (Apr 9, Apr 23, May 14,
      Jun 1; May 28 has an uncommitted pre-command draft — regenerate or reshape it)

## Recently done

- (2026-07-06) Added `/council-notes` project command (`.claude/commands/`, now tracked in
  git); validated on June 11. June 11 transcript names Caden re: the Flock ALPR records
  request — see that meeting's notes.

- (2026-07-03) Designed + implemented full pipeline, backfilled since April, pushed to GitHub.
- (2026-07-03) Full backfill complete: 7 meetings, all with agendas + Whisper-medium transcripts;
  3 June meetings also have official captions; audio opus published as release assets by CI.
  Whisper medium/MPS ran ~40x realtime on the M2 Max — full backlog in ~25 min, not hours.
