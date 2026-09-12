# upcoming/

Agenda previews for meetings that haven't happened yet, written by
`python3 scripts/hsvcc.py preview-agendas` (the Tuesday-evening CI run).

Each `<date>-<body>/` folder holds:

- `agenda.pdf` — the Legistar agenda, re-downloaded each run to catch amendments
- `event.json` — the raw Legistar event record
- `agenda-preview.md` — parsed topic summary + link-check results

After the meeting passes and the Friday sync has created the real
`meetings/<slug>/` folder, the preview markdown is copied there as
`agenda-preview.md` and the folder here is pruned.
