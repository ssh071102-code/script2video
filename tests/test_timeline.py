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


def test_tail_silence_covers_fade_after_quantization() -> None:
    # 0.4 + 1.01 + 0.4 = 1.81s rounds down to 1.80s (45 frames), which used
    # to leave only 0.39s of silence after the voice: less than the fade.
    tl = build_timeline([1.01, 1.0], fade=0.4, pad_head=0.4, pad_tail=0.4)
    s0 = tl.scenes[0]
    narration_end = s0.narration_start + s0.narration_duration
    tail = s0.video_end - narration_end
    assert tail >= tl.fade - 1e-9
    assert narration_end <= tl.xfade_offsets[0] + 1e-9


@pytest.mark.parametrize("narration", [0.5, 1.01, 1.013, 2.017, 3.339, 7.999])
@pytest.mark.parametrize("fps", [24, 25, 30])
def test_pads_hold_on_the_quantized_clock(narration: float, fps: int) -> None:
    tl = build_timeline([narration, narration], fps=fps, fade=0.4, pad_head=0.4, pad_tail=0.4)
    # Scene starts are stored rounded to 1 us, hence the 1e-6 tolerance.
    for s in tl.scenes:
        head = s.narration_start - s.video_start
        tail = s.video_end - (s.narration_start + s.narration_duration)
        assert head >= tl.fade - 1e-6
        assert tail >= tl.fade - 1e-6
        frames = s.visual_duration * fps
        assert frames == pytest.approx(round(frames))


def test_pad_check_uses_quantized_values() -> None:
    # At 10 fps both 0.38s and 0.4s land on 4 frames, so on the clock that
    # is actually rendered the pad equals the fade and is valid.
    tl = build_timeline([1.0], fps=10, fade=0.4, pad_head=0.38, pad_tail=0.38)
    assert tl.fade == 0.4
    with pytest.raises(ValueError, match="never overlaps a crossfade"):
        build_timeline([1.0], fps=10, fade=0.4, pad_head=0.34, pad_tail=0.4)
