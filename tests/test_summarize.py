from datetime import date
from pathlib import Path

import pytest

from summarize_agendas import (render_summary_md, source_hash, summarize,
                               summary_is_current)

TODAY = date(2026, 8, 18)
PREVIEW = "# Agenda preview\n\n- item\n"


def _make_upcoming(tmp_path: Path) -> Path:
    pdir = tmp_path / "upcoming" / "2026-08-27-city-council-regular-meeting"
    pdir.mkdir(parents=True)
    (pdir / "agenda-preview.md").write_text(PREVIEW, encoding="utf-8")
    return pdir


def test_skips_without_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SLAYDEN_API_TOKEN", raising=False)
    pdir = _make_upcoming(tmp_path)
    assert summarize(tmp_path / "upcoming", today=TODAY,
                     generate=lambda _: pytest.fail("should not call the API")) == 0
    assert not (pdir / "summary.md").exists()


def test_generates_summary_with_hash_marker(tmp_path: Path,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLAYDEN_API_TOKEN", "test-key")
    pdir = _make_upcoming(tmp_path)
    assert summarize(tmp_path / "upcoming", today=TODAY,
                     generate=lambda _: "- The city plans X\n") == 0
    text = (pdir / "summary.md").read_text(encoding="utf-8")
    assert "- The city plans X" in text
    assert f"source-sha256: {source_hash(PREVIEW)}" in text
    assert "AI-generated" in text


def test_skips_when_summary_matches_preview_hash(tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLAYDEN_API_TOKEN", "test-key")
    pdir = _make_upcoming(tmp_path)
    (pdir / "summary.md").write_text(render_summary_md("- old", PREVIEW, "2026-08-11"),
                                     encoding="utf-8")
    assert summarize(tmp_path / "upcoming", today=TODAY,
                     generate=lambda _: pytest.fail("hash unchanged; must not regen")) == 0


def test_regenerates_when_agenda_amended(tmp_path: Path,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLAYDEN_API_TOKEN", "test-key")
    pdir = _make_upcoming(tmp_path)
    (pdir / "summary.md").write_text(
        render_summary_md("- old", "different preview", "2026-08-11"), encoding="utf-8")
    assert not summary_is_current(pdir / "summary.md", PREVIEW)
    summarize(tmp_path / "upcoming", today=TODAY, generate=lambda _: "- new\n")
    assert "- new" in (pdir / "summary.md").read_text(encoding="utf-8")


def test_generation_failure_is_nonfatal(tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLAYDEN_API_TOKEN", "test-key")
    pdir = _make_upcoming(tmp_path)

    def boom(_: str) -> str:
        raise RuntimeError("api down")

    assert summarize(tmp_path / "upcoming", today=TODAY, generate=boom) == 0
    assert not (pdir / "summary.md").exists()
