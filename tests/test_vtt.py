from hsvcc import Cue, parse_vtt, render_captions_txt

SAMPLE = """WEBVTT

00:01:00.250 --> 00:01:01.680
Good evening everyone.

00:01:02.450 --> 00:01:06.809
It is Thursday, June 25th.

00:01:02.450 --> 00:01:06.809
It is Thursday, June 25th.

01:02:03.000 --> 01:02:04.000
Much later cue.
"""


def test_parse_vtt_extracts_cues() -> None:
    cues = parse_vtt(SAMPLE)
    assert cues[0] == Cue(start=60.25, text="Good evening everyone.")
    assert len(cues) == 4
    assert cues[3].start == 3723.0


def test_parse_vtt_handles_mm_ss_timestamps() -> None:
    cues = parse_vtt("WEBVTT\n\n01:00.500 --> 01:02.000\nHi.\n")
    assert cues == [Cue(start=60.5, text="Hi.")]


def test_render_dedups_and_adds_markers() -> None:
    out = render_captions_txt(SAMPLE)
    assert out.count("It is Thursday, June 25th.") == 1
    assert "[00:01:00]" in out
    assert "[01:02:03]" in out
