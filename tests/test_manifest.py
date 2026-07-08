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
