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
   ends; both pads must be >= the fade duration, which is validated here.

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
    visual_duration: float  # pad_head + narration + pad_tail, frame-quantized
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
    if min(pad_head, pad_tail) < fade:
        raise ValueError(
            f"pad_head ({pad_head}) and pad_tail ({pad_tail}) must both be "
            f">= fade ({fade}) so narration never overlaps a crossfade"
        )

    fade_q = _quantize(fade, fps)
    scenes: list[SceneTiming] = []
    cursor = 0.0
    for i, narration in enumerate(narration_durations):
        if narration <= 0:
            raise ValueError(f"scene {i}: narration duration must be > 0")
        visual = _quantize(pad_head + narration + pad_tail, fps)
        video_start = cursor - (fade_q if i > 0 else 0.0)
        scenes.append(
            SceneTiming(
                index=i,
                narration_duration=narration,
                visual_duration=visual,
                video_start=round(video_start, 6),
                narration_start=round(video_start + _quantize(pad_head, fps), 6),
            )
        )
        cursor = video_start + visual

    return Timeline(
        fps=fps,
        fade=fade_q,
        scenes=tuple(scenes),
        total_duration=round(cursor, 6),
    )
