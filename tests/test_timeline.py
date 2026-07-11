"""Known-answer tests for the frame-exact timeline math."""

import pytest

from script2video.timeline import build_timeline

# Defaults used throughout: fps=25, fade=0.4, pad_head=0.6, pad_tail=1.0.


def test_two_scene_known_answer() -> None:
    tl = build_timeline([2.0, 3.0])
    s0, s1 = tl.scenes

    assert s0.visual_duration == 3.6  # 0.6 + 2.0 + 1.0, exactly 90 frames
    assert s1.visual_duration == 4.6  # 115 frames
    assert s0.video_start == 0.0
    assert s1.video_start == 3.2  # 3.6 - 0.4 fade overlap
    assert s0.narration_start == 0.6
    assert s1.narration_start == 3.8
    assert tl.total_duration == 7.8  # 3.6 + 4.6 - 0.4
    assert tl.xfade_offsets == (3.2,)


def test_three_scene_offsets_accumulate_fade() -> None:
    tl = build_timeline([1.0, 1.0, 1.0])
    # visual = 2.6 each; starts at 0, 2.2, 4.4
    assert [s.video_start for s in tl.scenes] == [0.0, 2.2, 4.4]
    assert tl.total_duration == pytest.approx(7.0)
    assert tl.xfade_offsets == (2.2, 4.4)


def test_durations_are_quantized_to_whole_frames() -> None:
    tl = build_timeline([2.017], fps=30)
    frames = tl.scenes[0].visual_duration * 30
    assert frames == pytest.approx(round(frames))
    # 0.6 + 2.017 + 1.0 = 3.617s -> 108.51 frames -> rounds to 109
    assert round(frames) == 109


def test_fade_is_quantized_to_whole_frames() -> None:
    tl = build_timeline([2.0, 2.0], fps=24, fade=0.51)
    assert tl.fade * 24 == pytest.approx(round(tl.fade * 24))


def test_narration_never_overlaps_fade_window() -> None:
    tl = build_timeline([5.0, 5.0, 5.0])
    for scene, offset in zip(tl.scenes[:-1], tl.xfade_offsets):
        narration_end = scene.narration_start + scene.narration_duration
        assert narration_end <= offset + 1e-9


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"narration_durations": []}, "at least one scene"),
        ({"narration_durations": [1.0], "fps": 0}, "fps must be positive"),
        ({"narration_durations": [1.0], "fade": -0.1}, "fade must be"),
        ({"narration_durations": [1.0, -2.0]}, "must be > 0"),
        (
            {"narration_durations": [1.0], "fade": 0.8},
            "never overlaps a crossfade",
        ),
    ],
)
def test_invalid_inputs_raise(kwargs: dict, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        build_timeline(**kwargs)
