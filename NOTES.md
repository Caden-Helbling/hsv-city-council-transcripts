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

- [ ] Re-run `extract-votes` once Huntsville publishes Final minutes (all 2026 meetings are
      still Draft/Unapproved — every meeting's notes.md currently says "no roll-call recorded").
      When minutes go Final, notes.md decision tables can be reconciled against votes.json.

## Recently done

- (2026-08-09) Ran `/council-notes` on the **2026-07-23 regular meeting** → notes.md.
  Highlights: Harris Farms PDH approved (505 ac → ~1,800 homes, Ord 26-495), Northern
  Bypass 75% done + North Village phase 1 sold out (Target/Home Depot closings
  Aug–Sept), $30.0M expenditures, Aug 25 election machinery approved, emergency
  ladder-truck lease added same-night ($360/day), Museum Board reappointments
  postponed to Aug 13 (4/5 vote, Little absent), Flock ALPR public comment → Meredith's
  next town hall will be about Flock. This meeting has NO official captions (Castus
  404s the VTT) — whisper is its only transcript.
- (2026-08-09) Transcribed **2026-07-23 regular**, **2026-07-10 budget work session**,
  and **2026-07-23 northern-bypass clip** locally on **slayden's RTX 4080 SUPER**
  (whisper medium, ~1h50m main meeting in a few minutes). slayden is now a CUDA
  transcription node: installed torch 2.13.0+cu130 into the user Python 3.11 env
  (was CPU-only). Gotcha: `llama-server` holds ~15 GB of the 4080's 16 GB —
  `Stop-Service llama-server -Force` (also stops dependent `open-webui`) before
  transcribing, `Start-Service` both after.
- (2026-07-12) Ran `/council-notes` on **all remaining meetings** — every meeting in the repo now
  has a notes.md. New: Apr 9 (40 MW solar farm lease, Res 26-327), Apr 23 (Huntsville Hospital →
  Crestwood $450M acquisition; TIF 9 project plan launched, ~3,689.58 ac), May 14 (TIF 9 public
  hearing; "Microwave Dave" triple honor; $59.2M expenditures), May 28 (lodging-tax Ord 26-484
  *introduced*; TIF 9 *certified* only; Greenbrier rezone passed w/ Meredith NAY), Jun 1 (first
  Council/HCS joint work session since 2021 — discussion-only, no votes). Generated via 5 parallel
  fork agents; committed one-per-meeting.
- (2026-07-12) **TIF 9 does NOT fund a Lowe Mill↔Big Spring Park pedestrian bridge** (user Q).
  Verified against the binding `TIF 9 Project Plan Complete 7-7-26.pdf` (Legistar matter 8217,
  attachment 16186; 23 pp) — zero hits for bridge/pedestrian/big spring/lowe. TIF 9's 5 projects:
  VBC North Hall expansion (~$200M), North Huntsville Beltline Greenway ($5M, connects Big Spring
  going *north* to Oakwood), Mill Creek Park ($5M), Lowe *Avenue* school improvements ($5M),
  former federal courthouse reno. Lowe *Mill* is a carved-out county "tax island." The only
  pedestrian "sky bridge" (Pinhook Creek remediation) is separately federally funded, not TIF.

- (2026-07-12) Ran `/council-notes` on the **2026-07-09** meeting →
  `meetings/2026-07-09-city-council-meeting/notes.md`. Highlights: TIF 9 created
  (Res 26-592, 5 projects), lodging tax +1% for the VBC finally passed (Ord 26-484,
  after 3 postponements), Ryan Renaud declared elected to the school board unopposed,
  $21.9M expenditures. All by voice vote — no roll-calls (Draft minutes, no votes.json yet).

- (2026-07-12) Ran `/council-notes` on the **2026-07-09** meeting →
  `meetings/2026-07-09-city-council-meeting/notes.md`. Highlights: TIF 9 created
  (Res 26-592, 5 projects), lodging tax +1% for the VBC finally passed (Ord 26-484,
  after 3 postponements), Ryan Renaud declared elected to the school board unopposed,
  $21.9M expenditures. All by voice vote — no roll-calls (Draft minutes, no votes.json yet).

- (2026-07-12) Transcribed the **2026-07-09** meeting locally on **desktop-6npd885's GTX 1080 Ti**
  (~88 min → a few min; 13.5k words). This box is now a CUDA transcription node, not just the
  M2 Max: `transcribe` picked cpu on any non-Mac host, so it hardcoded the GPU idle — fixed to
  prefer cuda → mps → cpu with fp16 on CUDA (`scripts/hsvcc.py`). Needs `openai-whisper` installed
  (not in requirements; CI never transcribes) + torch-cu126 (already present here).

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
