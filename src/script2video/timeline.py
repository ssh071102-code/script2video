"""Frame-exact timeline math.

This is the heart of the assembly layer. Scenes crossfade into each other,
which means the global timeline is *shorter* than the sum of scene
durations, and every downstream artifact -- caption cue times, audio
delays, xfade offsets, the final ``-t`` duration -- must agree on the same
arithmetic. Doing this in one pure module keeps the whole pipeline
testable with known-answer cases.

Two invariants:

1. Everything is quantized to whole frames first. xfade offsets that do
   not land on frame boundaries produce off-by-one-frame seams; quantizing
   durations up front means every derived number is an exact multiple of
   ``1/fps``.
2. Narration never overlaps a crossfade. Each scene reserves ``pad_head``
   seconds of silence before the voice starts and ``pad_tail`` after it
   ends; both pads must be >= the fade duration after rounding to whole
   frames, which is validated here. Narration length is rounded *up* to a
   whole frame so rounding can never shave the tail pad.

Timeline layout for scene *i* (all in seconds on the global clock)::

    video_start[i]     = sum(visual[j] for j < i) - i * fade
    narration_start[i] = video_start[i] + pad_head
    total              = sum(visual) - (n - 1) * fade
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class SceneTiming:
    """Placement of one scene on the global timeline (seconds)."""

    index: int
    narration_duration: float
    visual_duration: float  # pad_head + narration (rounded up) + pad_tail, in whole frames
    video_start: float
    narration_start: float

    @property
    def video_end(self) -> float:
        return self.video_start + self.visual_duration


@dataclass(frozen=True)
class Timeline:
    """Global timeline for the whole video."""

    fps: int
    fade: float  # frame-quantized crossfade duration
    scenes: tuple[SceneTiming, ...]
    total_duration: float

    @property
    def xfade_offsets(self) -> tuple[float, ...]:
        """Start time of each crossfade = video_start of the incoming scene."""
        return tuple(s.video_start for s in self.scenes[1:])


def _quantize(seconds: float, fps: int) -> float:
    """Round *seconds* to the nearest whole frame count (half rounds up).

    ``round()`` would round half-frames to even (banker's rounding), which
    is a machine-independent but surprising rule for media timing; explicit
    half-up keeps quantization predictable.
    """
    return math.floor(seconds * fps + 0.5) / fps


def _ceil_frames(seconds: float, fps: int) -> float:
    """Round *seconds* up to a whole frame count.

    The small epsilon keeps float noise in ``seconds * fps`` (a measured
    duration that is a whole frame count plus 1e-12) from adding a frame.
    """
    return math.ceil(seconds * fps - 1e-6) / fps


def build_timeline(
    narration_durations: list[float],
    *,
    fps: int = 25,
    fade: float = 0.4,
    pad_head: float = 0.6,
    pad_tail: float = 1.0,
) -> Timeline:
    """Compute the frame-exact global timeline.

    ``narration_durations`` are the measured audio lengths per scene, in
    seconds. Raises :class:`ValueError` for empty input, non-positive
    durations, or pads shorter than the fade (which would let narration
    bleed into a crossfade).
    """
    if not narration_durations:
        raise ValueError("timeline needs at least one scene")
    if fps <= 0:
        raise ValueError(f"fps must be positive, got {fps}")
    if fade < 0:
        raise ValueError(f"fade must be >= 0, got {fade}")

    # Check the pads on the frame grid that is actually rendered: comparing
    # the raw values says nothing about the quantized layout.
    fade_q = _quantize(fade, fps)
    head_q = _quantize(pad_head, fps)
    tail_q = _quantize(pad_tail, fps)
    if min(head_q, tail_q) < fade_q:
        raise ValueError(
            f"pad_head ({pad_head}) and pad_tail ({pad_tail}) must both be "
            f">= fade ({fade}) after rounding to whole frames at {fps} fps, "
            "so narration never overlaps a crossfade"
        )

    scenes: list[SceneTiming] = []
    cursor = 0.0
    for i, narration in enumerate(narration_durations):
        if narration <= 0:
            raise ValueError(f"scene {i}: narration duration must be > 0")
        # Round the narration *up* to whole frames so the silence after it
        # is never shorter than the quantized tail pad.
        visual = _quantize(head_q + _ceil_frames(narration, fps) + tail_q, fps)
        video_start = cursor - (fade_q if i > 0 else 0.0)
        scenes.append(
            SceneTiming(
                index=i,
                narration_duration=narration,
                visual_duration=visual,
                video_start=round(video_start, 6),
                narration_start=round(video_start + head_q, 6),
            )
        )
        cursor = video_start + visual

    return Timeline(
        fps=fps,
        fade=fade_q,
        scenes=tuple(scenes),
        total_duration=round(cursor, 6),
    )
