"""Command line interface.

    script2video render examples/demo-script.md -o out/demo.mp4
    script2video render examples/demo-script.md --dry-run
    script2video captions examples/demo-script.md -o out/demo.srt
"""

from __future__ import annotations

from pathlib import Path

import typer

from . import __version__
from .errors import Script2VideoError
from .filtergraph import build_filtergraph
from .pipeline import RenderSettings, build_plan, captions_only, make_spec, render
from .script import parse_script

app = typer.Typer(
    add_completion=False,
    help="Turn a markdown script into a narrated, captioned video.",
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _fail(exc: Exception) -> None:
    typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


def _print_scene_table(plan) -> None:
    typer.echo("")
    typer.echo("scene  start      narration  visual   title")
    for scene_plan, timing in zip(plan.scenes, plan.timeline.scenes):
        mark = " (est)" if scene_plan.estimated else ""
        typer.echo(
            f"  {timing.index + 1}    {timing.video_start:7.2f}s   "
            f"{scene_plan.duration:6.2f}s{mark:6s}"
            f"{timing.visual_duration:6.2f}s   {scene_plan.scene.title}"
        )
    typer.echo(f"total  {plan.timeline.total_duration:7.2f}s")


@app.command(name="render")
def render_cmd(
    script_path: Path = typer.Argument(
        ..., metavar="SCRIPT", help="Markdown script file."
    ),
    output: Path = typer.Option(
        Path("out/video.mp4"), "--output", "-o", help="Output mp4 path."
    ),
    voice: str | None = typer.Option(
        None, "--voice", help="Override the script's TTS voice (edge-tts name)."
    ),
    width: int = typer.Option(1280, help="Output width in pixels."),
    height: int = typer.Option(720, help="Output height in pixels."),
    fps: int = typer.Option(25, help="Output frame rate."),
    crf: int = typer.Option(23, help="x264 quality (lower = larger/better)."),
    fade: float = typer.Option(0.4, help="Crossfade duration between scenes, seconds."),
    burn: bool = typer.Option(
        True, "--burn/--no-burn", help="Burn captions into the video."
    ),
    workdir: Path = typer.Option(
        Path(".script2video"),
        "--workdir",
        help="Working directory (narration cache, cards, intermediate files).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print the plan (scenes, timings, filtergraph) without rendering.",
    ),
) -> None:
    """Render SCRIPT to a narrated, captioned mp4."""
    settings = RenderSettings(
        width=width,
        height=height,
        fps=fps,
        crf=crf,
        fade=fade,
        voice=voice,
        burn_captions=burn,
    )
    typer.echo(f"script2video {__version__}")
    try:
        script = parse_script(script_path)
        typer.echo(
            f"script : {script_path.as_posix()} "
            f"({len(script.scenes)} scenes, voice {settings.voice or script.voice})"
        )
        if dry_run:
            plan, cached = build_plan(
                script, settings, workdir, allow_estimates=True
            )
            _print_scene_table(plan)
            graph = build_filtergraph(make_spec(plan, settings))
            chains = graph.split(";")
            typer.echo("")
            typer.echo(
                f"plan   : {len(plan.scenes)} inputs, "
                f"{len(plan.timeline.xfade_offsets)} crossfades at "
                f"{', '.join(f'{o:.2f}s' for o in plan.timeline.xfade_offsets)}"
            )
            typer.echo(
                f"cache  : {cached}/{len(plan.scenes)} scenes cached; "
                "durations marked (est) use a words-per-second estimate"
            )
            typer.echo(f"filtergraph ({len(chains)} chains):")
            for chain in chains:
                typer.echo(f"  {chain}")
            typer.echo("dry run: nothing rendered")
            return

        result = render(script, output, settings, workdir)
        cached = result.cached_scenes
        fresh = len(result.plan.scenes) - cached
        typer.echo(
            f"[1/4] narration  {fresh} synthesized, {cached} cached "
            f"({result.plan.word_count} word boundaries) "
            f"[{result.stage_seconds['narration']:.1f}s]"
        )
        typer.echo(
            f"[2/4] captions   {len(result.plan.cues)} cues -> captions.srt "
            f"[{result.stage_seconds['captions']:.1f}s]"
        )
        typer.echo(
            f"[3/4] backdrops  {len(result.plan.scenes)} cards at "
            f"{width * 2}x{height * 2} (2x supersampled) "
            f"[{result.stage_seconds['backdrops']:.1f}s]"
        )
        typer.echo(
            f"[4/4] assembly   xfade chain + "
            f"{'caption burn-in' if burn else 'no burn-in'}, "
            f"crf {crf} [{result.stage_seconds['assembly']:.1f}s]"
        )
        _print_scene_table(result.plan)
        video = result.probe.video
        audio = result.probe.audio
        typer.echo("")
        typer.echo(
            f"output : {output.as_posix()} "
            f"({result.size_bytes / 1_048_576:.2f} MiB, {result.probe.duration:.2f}s, "
            f"{video.codec} {video.width}x{video.height}"
            f" + {audio.codec} {audio.sample_rate} Hz)"
        )
    except Script2VideoError as exc:
        _fail(exc)


@app.command()
def captions(
    script_path: Path = typer.Argument(
        ..., metavar="SCRIPT", help="Markdown script file."
    ),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Output .srt path (default: <script>.srt)."
    ),
    voice: str | None = typer.Option(
        None, "--voice", help="Override the script's TTS voice."
    ),
    workdir: Path = typer.Option(
        Path(".script2video"), "--workdir", help="Working directory / narration cache."
    ),
) -> None:
    """Write the SRT captions for SCRIPT (no video render).

    Cue times match a full render with the same settings, so the SRT can
    be used as a sidecar for a previously rendered video.
    """
    settings = RenderSettings(voice=voice)
    try:
        script = parse_script(script_path)
        srt, plan = captions_only(script, settings, workdir)
        target = output or script_path.with_suffix(".srt")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(srt, encoding="utf-8")
        typer.echo(
            f"wrote {target.as_posix()}: {len(plan.cues)} cues, "
            f"{plan.word_count} word boundaries, "
            f"{plan.timeline.total_duration:.2f}s timeline"
        )
    except Script2VideoError as exc:
        _fail(exc)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"script2video {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True
    ),
) -> None:
    """Markdown script in, narrated + captioned video out."""


def main() -> None:  # console_scripts entry point
    app()


if __name__ == "__main__":
    main()
