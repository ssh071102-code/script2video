"""Exact-argv tests: known timeline in, byte-identical ffmpeg command out."""

import pytest

from script2video.filtergraph import (
    CAPTION_FORCE_STYLE,
    RenderSpec,
    SceneFiles,
    build_filtergraph,
    build_render_args,
    escape_filter_path,
)
from script2video.timeline import build_timeline


def two_scene_spec(**overrides) -> RenderSpec:
    timeline = build_timeline([2.0, 3.0])  # known answer: see test_timeline
    defaults = dict(
        timeline=timeline,
        scenes=(
            SceneFiles("cards/scene_00.png", "tts/aaaa.mp3", "zoom-in"),
            SceneFiles("cards/scene_01.png", "tts/bbbb.mp3", "pan-right"),
        ),
        width=854,
        height=480,
        crf=27,
    )
    defaults.update(overrides)
    return RenderSpec(**defaults)


EXPECTED_GRAPH = (
    "[0:v]zoompan=z='1+0.10*on/90':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2'"
    ":d=90:s=854x480:fps=25,format=yuv420p,setsar=1[v0];"
    "[1:v]zoompan=z='1.08':x='(iw-iw/zoom)*on/115':y='(ih-ih/zoom)/2'"
    ":d=115:s=854x480:fps=25,format=yuv420p,setsar=1[v1];"
    "[v0][v1]xfade=transition=fade:duration=0.400:offset=3.200[vx];"
    f"[vx]subtitles=filename='captions.srt':force_style='{CAPTION_FORCE_STYLE}'[vout];"
    "[2:a]aresample=48000,adelay=600:all=1[a0];"
    "[3:a]aresample=48000,adelay=3800:all=1[a1];"
    "[a0][a1]amix=inputs=2:duration=longest:normalize=0,"
    "apad=whole_dur=7.800,atrim=end=7.800[aout]"
)


def test_filtergraph_exact() -> None:
    assert build_filtergraph(two_scene_spec()) == EXPECTED_GRAPH


def test_render_args_exact() -> None:
    assert build_render_args(two_scene_spec()) == [
        "-y", "-nostdin", "-loglevel", "error",
        "-i", "cards/scene_00.png",
        "-i", "cards/scene_01.png",
        "-i", "tts/aaaa.mp3",
        "-i", "tts/bbbb.mp3",
        "-filter_complex", EXPECTED_GRAPH,
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "27",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "96k",
        "-ar", "48000",
        "-movflags", "+faststart",
        "-t", "7.800",
        "render.mp4",
    ]


def test_argv_is_deterministic() -> None:
    assert build_render_args(two_scene_spec()) == build_render_args(two_scene_spec())


def test_single_scene_has_no_xfade() -> None:
    timeline = build_timeline([2.0])
    spec = RenderSpec(
        timeline=timeline,
        scenes=(SceneFiles("cards/scene_00.png", "tts/aaaa.mp3", "zoom-out"),),
        width=854,
        height=480,
    )
    graph = build_filtergraph(spec)
    assert "xfade" not in graph
    assert "[v0]null[vx]" in graph


def test_no_burn_in_when_srt_disabled() -> None:
    graph = build_filtergraph(two_scene_spec(srt=None))
    assert "subtitles" not in graph
    assert "[vx]null[vout]" in graph


def test_scene_count_mismatch_rejected() -> None:
    timeline = build_timeline([2.0, 3.0])
    with pytest.raises(ValueError, match="scene files"):
        RenderSpec(
            timeline=timeline,
            scenes=(SceneFiles("a.png", "a.mp3", "zoom-in"),),
            width=854,
            height=480,
        )


def test_escape_filter_path() -> None:
    assert escape_filter_path("a:b'c\\d") == "a\\:b\\'c\\\\d"
    assert escape_filter_path("captions.srt") == "captions.srt"
