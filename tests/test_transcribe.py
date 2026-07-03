import sys
import types
from pathlib import Path
from typing import Any

from hsvcc import Manifest, segments_to_srt, transcribe
from test_fetch_audio import make_meeting


def test_segments_to_srt() -> None:
    srt = segments_to_srt([{"start": 0.0, "end": 1.5, "text": " Hello."},
                           {"start": 61.0, "end": 62.0, "text": " World."}])
    assert srt.startswith("1\n00:00:00,000 --> 00:00:01,500\nHello.\n")
    assert "2\n00:01:01,000 --> 00:01:02,000\nWorld.\n" in srt


def test_transcribe_writes_outputs(tmp_path: Path) -> None:
    meetings, audio = tmp_path / "m", tmp_path / "a"
    m = make_meeting(meetings)
    audio.mkdir(parents=True)
    (audio / f"{m.slug}.opus").write_bytes(b"opus")

    fake = types.ModuleType("whisper")

    def load_model(name: str, device: str = "cpu") -> Any:
        class Model:
            def transcribe(self, path: str, **kw: Any) -> dict:
                return {"text": "Full transcript.",
                        "segments": [{"start": 0.0, "end": 1.0, "text": " Full transcript."}]}
        return Model()

    fake.load_model = load_model  # type: ignore[attr-defined]
    sys.modules["whisper"] = fake
    try:
        rc = transcribe([m.slug], False, meetings, audio)
    finally:
        del sys.modules["whisper"]
    assert rc == 0
    tdir = meetings / m.slug / "transcript"
    assert (tdir / "whisper-medium.txt").read_text() == "Full transcript.\n"
    assert (tdir / "whisper-medium.srt").exists()
    assert Manifest.load(meetings / m.slug).status["has_whisper"] is True
