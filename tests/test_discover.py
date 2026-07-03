from datetime import date
from pathlib import Path

from fakes import FakeSession
from hsvcc import Manifest, discover


def test_discover_creates_meeting_folder(tmp_path: Path) -> None:
    failures = discover(date(2026, 4, 1), tmp_path, FakeSession())  # type: ignore[arg-type]
    assert failures == 0
    mdir = tmp_path / "2026-06-25-city-council-meeting"
    m = Manifest.load(mdir)
    assert m.castus_id == "6a3dcff79537260002c64cd9"
    assert m.mp4_url == "https://cdn/out_1080.mp4"
    assert m.legistar_event_id == 1223
    assert (mdir / "captions.vtt").exists()
    assert "[00:01:00]" in (mdir / "captions.txt").read_text()
    assert (mdir / "agenda.pdf").read_bytes() == b"%PDF-fake"
    assert m.status["has_agenda"] and m.status["has_captions"]


def test_discover_idempotent(tmp_path: Path) -> None:
    discover(date(2026, 4, 1), tmp_path, FakeSession())  # type: ignore[arg-type]
    s2 = FakeSession()
    discover(date(2026, 4, 1), tmp_path, s2)  # type: ignore[arg-type]
    assert not any(u.endswith(".pdf") or ".vtt" in u for u in s2.calls)


def test_discover_counts_failures(tmp_path: Path) -> None:
    failures = discover(date(2026, 4, 1), tmp_path, FakeSession(video_status=500))  # type: ignore[arg-type]
    assert failures == 1
    assert not (tmp_path / "2026-06-25-city-council-meeting").exists()
