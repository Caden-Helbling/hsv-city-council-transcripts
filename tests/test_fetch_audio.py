from pathlib import Path
from typing import Any

from fakes import FakeSession
from hsvcc import Manifest, fetch_audio


class FakeRun:
    def __init__(self, fail_prefixes: tuple[str, ...] = ()) -> None:
        self.commands: list[list[str]] = []
        self.fail_prefixes = fail_prefixes

    def __call__(self, cmd: list[str], **kwargs: Any) -> Any:
        self.commands.append(cmd)
        rc = 1 if any(" ".join(cmd).startswith(p) for p in self.fail_prefixes) else 0
        if rc == 0 and cmd[0] == "ffmpeg":
            Path(cmd[-1]).write_bytes(b"opus")

        class R:
            returncode = rc
        return R()


def make_meeting(meetings_dir: Path) -> Manifest:
    m = Manifest(slug="2026-06-25-city-council-meeting", title="t", date="2026-06-25",
                 body=None, video_page_url="u", castus_id="abc",
                 mp4_url="https://cdn/out_1080.mp4", legistar_event_id=None,
                 legistar_url=None, agenda_url=None, minutes_url=None,
                 audio_asset_tag="audio-2026-06-25-city-council-meeting")
    m.save(meetings_dir / m.slug)
    return m


def test_fetch_audio_prefers_release_asset(tmp_path: Path) -> None:
    meetings, audio = tmp_path / "m", tmp_path / "a"
    m = make_meeting(meetings)
    run = FakeRun()

    def gh_run(cmd: list[str], **kw: Any) -> Any:
        audio.mkdir(parents=True, exist_ok=True)
        (audio / f"{m.slug}.opus").write_bytes(b"opus")
        return run(cmd, **kw)

    rc = fetch_audio([m.slug], False, False, meetings, audio, FakeSession(), run=gh_run)  # type: ignore[arg-type]
    assert rc == 0
    assert run.commands[0][:3] == ["gh", "release", "download"]
    assert not any(c[0] == "ffmpeg" for c in run.commands)


def test_fetch_audio_falls_back_to_mp4(tmp_path: Path) -> None:
    meetings, audio = tmp_path / "m", tmp_path / "a"
    m = make_meeting(meetings)
    run = FakeRun(fail_prefixes=("gh release download",))
    rc = fetch_audio([m.slug], False, False, meetings, audio, FakeSession(), run=run)  # type: ignore[arg-type]
    assert rc == 0
    assert any(c[0] == "ffmpeg" for c in run.commands)
    assert not (audio / f"{m.slug}.mp4").exists()
    assert (audio / f"{m.slug}.opus").exists()


def test_fetch_audio_publish_uploads_release(tmp_path: Path) -> None:
    meetings, audio = tmp_path / "m", tmp_path / "a"
    m = make_meeting(meetings)
    run = FakeRun()
    rc = fetch_audio([m.slug], False, True, meetings, audio, FakeSession(), run=run)  # type: ignore[arg-type]
    assert rc == 0
    assert any(c[:3] == ["gh", "release", "create"] for c in run.commands)
    assert Manifest.load(meetings / m.slug).status["has_audio_asset"] is True
