"""Deterministic ffmpeg command construction.

This module is pure: given a :class:`~script2video.timeline.Timeline`,
file names, and settings, it returns the exact ffmpeg argv. No filesystem
access, no randomness, no clocks. That buys two things:

* Testability -- unit tests assert the full argv/filtergraph for known
  inputs, so a regression in assembly logic fails a string comparison
  instead of producing a subtly broken video.
* Portability -- ffmpeg is executed with ``cwd`` set to the working
  directory and every path in the graph is a bare *file name* inside it.
  Absolute paths never enter the argv, which sidesteps platform quoting
  rules (Windows drive-letter colons inside filter strings) and makes the
  argv byte-identical across machines.

Graph shape for N scenes::

    [i:v]  zoompan (Ken Burns) -> [vI]          one per scene
    [v0][v1] xfade ... [vN-1] xfade -> chain    crossfades at exact offsets
    chain -> subtitles (optional burn-in) -> [vout]
    [N+i:a] aresample + adelay -> [aI]          narration onto the global clock
    [a0]..[aN-1] amix -> apad -> atrim -> [aout]
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .timeline import Timeline

# Ken Burns motion expressions. `on` is the output frame index; `frames`
# is substituted per scene. Zoom amplitude 0.10 over the scene, pans at a
# fixed 1.08 zoom. Cards are supersampled 2x, so zoompan only downscales.
_MOTIONS = {
    "zoom-in": (
        "1+0.10*on/{frames}",
        "(iw-iw/zoom)/2",
        "(ih-ih/zoom)/2",
    ),
    "zoom-out": (
        "1.10-0.10*on/{frames}",
        "(iw-iw/zoom)/2",
        "(ih-ih/zoom)/2",
    ),
    "pan-left": (  # frame travels right to left across the card
        "1.08",
        "(iw-iw/zoom)*(1-on/{frames})",
        "(ih-ih/zoom)/2",
    ),
    "pan-right": (
        "1.08",
        "(iw-iw/zoom)*on/{frames}",
        "(ih-ih/zoom)/2",
    ),
}

CAPTION_FORCE_STYLE = (
    "FontName=Arial,FontSize=14,PrimaryColour=&H00FFFFFF,"
    "OutlineColour=&H66000000,BorderStyle=1,Outline=1,Shadow=0.6,"
    "MarginV=22,Spacing=0.2"
)


@dataclass(frozen=True)
class SceneFiles:
    """Workdir-relative file names for one scene."""

    card: str  # e.g. "cards/scene_00.png"
    narration: str  # e.g. "tts/1a2b3c4d5e6f7a8b.mp3"
    motion: str  # key into _MOTIONS


@dataclass(frozen=True)
class RenderSpec:
    """Everything the argv builder needs, already resolved."""

    timeline: Timeline
    scenes: tuple[SceneFiles, ...]
    width: int
    height: int
    crf: int = 23
    audio_bitrate: str = "96k"
    sample_rate: int = 48000
    srt: str | None = "captions.srt"  # None disables burn-in
    output: str = "render.mp4"
    force_style: str = CAPTION_FORCE_STYLE

    def __post_init__(self) -> None:
        if len(self.scenes) != len(self.timeline.scenes):
            raise ValueError(
                f"{len(self.scenes)} scene files for "
                f"{len(self.timeline.scenes)} timeline entries"
            )


def escape_filter_path(name: str) -> str:
    """Escape a path for use inside a filter option value.

    ffmpeg's filter parser treats ``\\ ' :`` specially; escape them so the
    value survives one level of filter-option parsing. Kept for users who
    point the builder at nested paths -- the pipeline itself only emits
    bare file names.
    """
    out = []
    for ch in name:
        if ch in ("\\", "'", ":"):
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def _fmt(seconds: float) -> str:
    """Fixed-precision seconds for deterministic argv strings."""
    return f"{seconds:.3f}"


def build_filtergraph(spec: RenderSpec) -> str:
    """Build the complete ``-filter_complex`` graph."""
    tl = spec.timeline
    n = len(tl.scenes)
    parts: list[str] = []

    for i, (timing, files) in enumerate(zip(tl.scenes, spec.scenes)):
        frames = round(timing.visual_duration * tl.fps)
        z, x, y = (expr.format(frames=frames) for expr in _MOTIONS[files.motion])
        parts.append(
            f"[{i}:v]zoompan=z='{z}':x='{x}':y='{y}':d={frames}"
            f":s={spec.width}x{spec.height}:fps={tl.fps},"
            f"format=yuv420p,setsar=1[v{i}]"
        )

    last = "[v0]"
    for k, offset in enumerate(tl.xfade_offsets):
        out = f"[x{k}]" if k < n - 2 else "[vx]"
        parts.append(
            f"{last}[v{k + 1}]xfade=transition=fade"
            f":duration={_fmt(tl.fade)}:offset={_fmt(offset)}{out}"
        )
        last = out
    if n == 1:
        parts.append("[v0]null[vx]")

    if spec.srt is not None:
        parts.append(
            f"[vx]subtitles=filename='{escape_filter_path(spec.srt)}'"
            f":force_style='{spec.force_style}'[vout]"
        )
    else:
        parts.append("[vx]null[vout]")

    for i, timing in enumerate(tl.scenes):
        delay_ms = round(timing.narration_start * 1000)
        parts.append(
            f"[{n + i}:a]aresample={spec.sample_rate},"
            f"adelay={delay_ms}:all=1[a{i}]"
        )
    mix_inputs = "".join(f"[a{i}]" for i in range(n))
    parts.append(
        f"{mix_inputs}amix=inputs={n}:duration=longest:normalize=0,"
        f"apad=whole_dur={_fmt(tl.total_duration)},"
        f"atrim=end={_fmt(tl.total_duration)}[aout]"
    )
    return ";".join(parts)


def build_render_args(spec: RenderSpec) -> list[str]:
    """Build the full ffmpeg argv (excluding the executable itself).

    All input/output paths are workdir-relative by construction; run with
    ``cwd`` set to the working directory (see ``media.run_ffmpeg``).
    """
    args: list[str] = ["-y", "-nostdin", "-loglevel", "error"]
    for files in spec.scenes:
        args += ["-i", files.card]
    for files in spec.scenes:
        args += ["-i", files.narration]
    args += [
        "-filter_complex",
        build_filtergraph(spec),
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        str(spec.crf),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        spec.audio_bitrate,
        "-ar",
        str(spec.sample_rate),
        "-movflags",
        "+faststart",
        "-t",
        _fmt(spec.timeline.total_duration),
        spec.output,
    ]
    return args
