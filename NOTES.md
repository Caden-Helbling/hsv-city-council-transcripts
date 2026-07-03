# Project notes

Cross-session state for this repo. (This is a personal project — notes live
here, not in caden-work-machine.)

## Key technical facts (hard-won, undocumented APIs)

- Videos are on **Castus TV VOD** (`cloud.castus.tv/vod/hsv-tv/embed/<id>`), iframe on each
  `huntsvilleal.gov/videos/<slug>/` page.
- MP4 resolve: `POST https://imd0mxanj2.execute-api.us-west-2.amazonaws.com/upload/get`
  body `{"file": "<id>", "type": "vod", "user": ""}` → unsigned CloudFront URL (~1.6 GB, 1080p only).
- Captions: `POST .../upload/get-captions` body `{"file": {"_id": "<id>"}, "user": {"_id": ""}}`
  → signed S3 URL for WebVTT. **Only recent videos have VTTs** (June 2026 yes, April/May 404) —
  Whisper is the only transcript source for older meetings.
- Meeting list: scrape `huntsvilleal.gov/videocategory/city-council-meetings/` (+ `page/N/`);
  WP REST API for the `videos` post type is disabled.
- Agendas: Legistar Web API `webapi.legistar.com/v1/huntsvilleal/events` (OData filters work).

## Next up

- [ ] Verify first scheduled Action run (Friday) commits cleanly
- [ ] Consider a `/council-notes` slash command for LLM note generation against a meeting folder
- [ ] Backfilled 7 meetings (2026-04-09 → 2026-06-25); Whisper transcripts kicked off 2026-07-03,
      check `meetings/*/transcript/` and commit + push when done (`git pull` first — CI commits manifest flags)

## Recently done

- (2026-07-03) Designed + implemented full pipeline, backfilled since April, pushed to GitHub,
  dispatched first CI run.
