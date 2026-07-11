"""Pipeline orchestration: script -> narration -> captions -> cards -> mp4.

Only this module touches the filesystem layout of the working directory::

    <workdir>/
        tts/            narration audio + word boundary JSON (cache)
        cards/          generated scene backdrops (PNG, 2x supersampled)
        captions.srt    burned-in / exported captions
        render.mp4      ffmpeg output, moved to the requested path

The working directory doubles as a cache: narration is keyed by
(voice, rate, text), so repeated renders and the ``captions`` command
never re-synthesize unchanged scenes.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from .backdrop import SUPERSAMPLE, write_card
from .captions import CaptionStyle, Cue, group_words, to_srt
from .errors import NarrationError
from .filtergraph import RenderSpec, SceneFiles, build_render_args
from .media import ProbeResult, probe, run_ffmpeg
from .palettes import get_palette
from .script import Scene, Script
from .timeline import Timeline, build_timeline
from .tts import DEFAULT_RATE, Narration, load_cached, synthesize

# Rough speaking speed used only by --dry-run when narration is not cached.
ESTIMATE_WORDS_PER_SECOND = 2.9


@dataclass(frozen=True)
class RenderSettings:
    """User-facing knobs, shared by render / captions / dry-run."""

    width: int = 1280
    height: int = 720
    fps: int = 25
    crf: int = 23
    fade: float = 0.4
    pad_head: float = 0.6
    pad_tail: float = 1.0
    voice: str | None = None  # None: use the script's voice
    rate: str = DEFAULT_RATE
    burn_captions: bool = True
    captions: CaptionStyle = field(default_factory=CaptionStyle)


@dataclass(frozen=True)
class ScenePlan:
    scene: Scene
    duration: float
    narration: Narration | None  # None only when estimated (dry-run)

    @property
    def estimated(self) -> bool:
        return self.narration is None


@dataclass(frozen=True)
class Plan:
    script: Script
    voice: str
    scenes: tuple[ScenePlan, ...]
    timeline: Timeline
    cues: tuple[Cue, ...]

    @property
    def word_count(self) -> int:
        return sum(len(p.narration.words) for p in self.scenes if p.narration)

    @property
    def synthesized(self) -> int:
        return sum(1 for p in self.scenes if p.narration is not None)


@dataclass(frozen=True)
class RenderResult:
    plan: Plan
    output: Path
    size_bytes: int
    probe: ProbeResult
    stage_seconds: dict[str, float]
    cached_scenes: int


def _tts_dir(workdir: Path) -> Path:
    return workdir / "tts"


def build_plan(
    script: Script,
    settings: RenderSettings,
    workdir: Path,
    *,
    allow_estimates: bool = False,
) -> tuple[Plan, int]:
    """Resolve narration for every scene and lay out the global timeline.

    Returns ``(plan, cached_count)``. With ``allow_estimates=True`` scenes
    missing from the cache are estimated from word count instead of hitting
    the network (used by ``--dry-run``).
    """
    voice = settings.voice or script.voice
    cache = _tts_dir(workdir)
    plans: list[ScenePlan] = []
    cached = 0
    for scene in script.scenes:
        narration = load_cached(scene.narration, voice, cache, rate=settings.rate)
        if narration is not None:
            cached += 1
        elif allow_estimates:
            words = len(scene.narration.split())
            plans.append(
                ScenePlan(scene, round(max(1.2, words / ESTIMATE_WORDS_PER_SECOND), 2), None)
            )
            continue
        else:
            narration = synthesize(
                scene.narration, voice, cache, rate=settings.rate
            )
        plans.append(ScenePlan(scene, narration.duration, narration))

    timeline = build_timeline(
        [p.duration for p in plans],
        fps=settings.fps,
        fade=settings.fade,
        pad_head=settings.pad_head,
        pad_tail=settings.pad_tail,
    )
    cues = build_cues(plans, timeline, settings.captions)
    plan = Plan(
        script=script,
        voice=voice,
        scenes=tuple(plans),
        timeline=timeline,
        cues=tuple(cues),
    )
    return plan, cached


def build_cues(
    plans: list[ScenePlan], timeline: Timeline, style: CaptionStyle
) -> list[Cue]:
    """Shift each scene's word timings onto the global clock and group them.

    Grouping is done per scene so a caption never spans a crossfade.
    """
    cues: list[Cue] = []
    for plan, timing in zip(plans, timeline.scenes):
        if plan.narration is None:
            continue
        shifted = [w.shifted(timing.narration_start) for w in plan.narration.words]
        cues.extend(group_words(shifted, style))
    return cues


def make_spec(plan: Plan, settings: RenderSettings) -> RenderSpec:
    scenes = tuple(
        SceneFiles(
            card=f"cards/scene_{p.scene.index:02d}.png",
            narration=(
                f"tts/{p.narration.audio_path.name}"
                if p.narration
                else f"tts/scene_{p.scene.index:02d}.mp3"  # dry-run placeholder
            ),
            motion=p.scene.motion,
        )
        for p in plan.scenes
    )
    return RenderSpec(
        timeline=plan.timeline,
        scenes=scenes,
        width=settings.width,
        height=settings.height,
        crf=settings.crf,
        srt="captions.srt" if settings.burn_captions and plan.cues else None,
    )


def render(
    script: Script,
    output: Path,
    settings: RenderSettings,
    workdir: Path,
) -> RenderResult:
    """Run the full pipeline and write the final video to *output*."""
    workdir.mkdir(parents=True, exist_ok=True)
    stage_seconds: dict[str, float] = {}

    t0 = time.perf_counter()
    plan, cached = build_plan(script, settings, workdir)
    stage_seconds["narration"] = time.perf_counter() - t0
    for scene_plan in plan.scenes:
        if scene_plan.narration is None:  # pragma: no cover - defensive
            raise NarrationError(f"scene {scene_plan.scene.index}: no narration")

    t0 = time.perf_counter()
    srt_path = workdir / "captions.srt"
    srt_path.write_text(to_srt(list(plan.cues)), encoding="utf-8")
    stage_seconds["captions"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    spec = make_spec(plan, settings)
    for scene_plan, files in zip(plan.scenes, spec.scenes):
        write_card(
            workdir / files.card,
            title=scene_plan.scene.title,
            kicker=f"scene {scene_plan.scene.index + 1:02d}",
            palette=get_palette(scene_plan.scene.palette),
            output_size=(settings.width, settings.height),
            seed=scene_plan.scene.index,
            image=scene_plan.scene.image,
        )
    stage_seconds["backdrops"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    run_ffmpeg(build_render_args(spec), cwd=workdir)
    stage_seconds["assembly"] = time.perf_counter() - t0

    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(workdir / spec.output), str(output))

    return RenderResult(
        plan=plan,
        output=output,
        size_bytes=output.stat().st_size,
        probe=probe(output),
        stage_seconds=stage_seconds,
        cached_scenes=cached,
    )


def captions_only(
    script: Script, settings: RenderSettings, workdir: Path
) -> tuple[str, Plan]:
    """Produce the SRT document (synthesizing narration if not cached)."""
    workdir.mkdir(parents=True, exist_ok=True)
    plan, _ = build_plan(script, settings, workdir)
    return to_srt(list(plan.cues)), plan
