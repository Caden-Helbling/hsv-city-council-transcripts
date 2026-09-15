from pathlib import Path

from hsvcc import Manifest, recompute_status


def make_manifest() -> Manifest:
    return Manifest(
        slug="2026-06-25-city-council-meeting",
        title="Huntsville City Council Meeting – June 25, 2026",
        date="2026-06-25",
        body="City Council Regular Meeting",
        video_page_url="https://www.huntsvilleal.gov/videos/x/",
        castus_id="abc",
        mp4_url="https://cdn/x.mp4",
        legistar_event_id=1223,
        legistar_url="https://huntsvilleal.legistar.com/MeetingDetail.aspx?LEGID=1223",
        agenda_url="https://cdn/agenda.pdf",
        minutes_url=None,
        audio_asset_tag="audio-2026-06-25-city-council-meeting",
    )


def test_manifest_round_trip(tmp_path: Path) -> None:
    m = make_manifest()
    m.save(tmp_path)
    loaded = Manifest.load(tmp_path)
    assert loaded == m
    assert (tmp_path / "meeting.json").read_text().endswith("\n")


def test_recompute_status_from_disk(tmp_path: Path) -> None:
    m = make_manifest()
    m.status["has_audio_asset"] = True
    (tmp_path / "agenda.pdf").write_bytes(b"%PDF")
    (tmp_path / "captions.vtt").write_text("WEBVTT\n")
    (tmp_path / "transcript").mkdir()
    (tmp_path / "transcript" / "whisper-medium.txt").write_text("hi")
    recompute_status(tmp_path, m)
    assert m.status == {"has_agenda": True, "has_minutes": False, "has_captions": True,
                        "has_audio_asset": True, "has_whisper": True, "has_votes": False}


def test_notes_round_trip_and_omitted_when_empty(tmp_path: Path) -> None:
    m = make_manifest()
    m.save(tmp_path)
    assert "notes" not in (tmp_path / "meeting.json").read_text()
    m.notes = ["Fetched by hand."]
    m.save(tmp_path)
    assert Manifest.load(tmp_path) == m


def test_load_names_the_offending_file(tmp_path: Path) -> None:
    (tmp_path / "meeting.json").write_text('{"slug": "x", "minutes_status": "Draft"}')
    try:
        Manifest.load(tmp_path)
    except ValueError as e:
        assert "meeting.json" in str(e) and "minutes_status" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_every_archived_manifest_loads() -> None:
    # a hand-edited meeting.json that drifts from the schema breaks every
    # command that sweeps meetings/ - catch it here, not in CI four days later
    meetings = Path(__file__).resolve().parents[1] / "meetings"
    for mdir in sorted(p for p in meetings.iterdir() if p.is_dir()):
        if (mdir / "meeting.json").exists():
            Manifest.load(mdir)
