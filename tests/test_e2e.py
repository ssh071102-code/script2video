"""End-to-end assembly from committed fixtures -- no network, real ffmpeg.

The narration cache is pre-seeded from tests/fixtures/narration (real
edge-tts output committed to the repo), so the full pipeline -- parse,
timeline, captions, backdrops, ffmpeg assembly, burn-in -- runs offline
and produces an actual mp4 that is then probed for validity.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from script2video.cli import app
from script2video.media import probe
from script2video.pipeline import RenderSettings, captions_only, render
from script2video.script import parse_script

SETTINGS = RenderSettings(width=640, height=360, fps=25, crf=30)
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def rendered(tmp_path_factory: pytest.TempPathFactory):
    """Render the fixture script once for the whole module."""
    import shutil

    tmp = tmp_path_factory.mktemp("e2e")
    workdir = tmp / "workdir"
    (workdir / "tts").mkdir(parents=True)
    for file in (FIXTURES / "narration").iterdir():
        if file.suffix in (".mp3", ".json"):
            shutil.copy(file, workdir / "tts" / file.name)

    script = parse_script(FIXTURES / "fixture-script.md")
    output = tmp / "out" / "fixture.mp4"
    result = render(script, output, SETTINGS, workdir)
    return output, result, workdir


def test_render_produces_a_file(rendered) -> None:
    output, result, _ = rendered
    assert output.is_file()
    assert result.size_bytes == output.stat().st_size > 10_000
    assert result.cached_scenes == 2  # nothing was synthesized


def test_output_probes_valid_with_full_decode(rendered) -> None:
    output, result, _ = rendered
    info = probe(output, decode=True)
    assert info.decode_errors == ()
    assert info.video is not None and info.audio is not None
    assert (info.video.codec, info.video.width, info.video.height) == (
        "h264",
        640,
        360,
    )
    assert info.audio.codec == "aac"
    assert info.audio.sample_rate == 48000
    # Container duration matches the computed timeline within a frame or two.
    assert info.duration == pytest.approx(
        result.plan.timeline.total_duration, abs=0.2
    )


def test_captions_and_srt_are_on_the_global_clock(rendered) -> None:
    _, result, workdir = rendered
    cues = result.plan.cues
    assert cues, "fixture render must produce caption cues"
    tl = result.plan.timeline
    assert cues[0].start == pytest.approx(tl.scenes[0].narration_start, abs=0.35)
    for cue in cues:
        assert 0 <= cue.start < cue.end <= tl.total_duration + 1e-6
    srt = workdir / "captions.srt"
    assert srt.is_file()
    assert "-->" in srt.read_text(encoding="utf-8")


def test_captions_only_offline(offline_workdir: Path, fixture_script_path: Path) -> None:
    script = parse_script(fixture_script_path)
    srt, plan = captions_only(script, SETTINGS, offline_workdir)
    assert srt.startswith("1\n00:00:00,")
    assert len(plan.cues) >= 2
    assert plan.word_count > 10


def test_cli_dry_run_offline(offline_workdir: Path, fixture_script_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "render",
            str(fixture_script_path),
            "--dry-run",
            "--workdir",
            str(offline_workdir),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "2/2 scenes cached" in result.output
    assert "xfade" in result.output
    assert "dry run: nothing rendered" in result.output


def test_cli_captions_offline(
    offline_workdir: Path, fixture_script_path: Path, tmp_path: Path
) -> None:
    runner = CliRunner()
    target = tmp_path / "fixture.srt"
    result = runner.invoke(
        app,
        [
            "captions",
            str(fixture_script_path),
            "-o",
            str(target),
            "--workdir",
            str(offline_workdir),
        ],
    )
    assert result.exit_code == 0, result.output
    assert target.is_file()
    assert "cues" in result.output


def test_cli_reports_script_errors(tmp_path: Path) -> None:
    bad = tmp_path / "bad.md"
    bad.write_text("## Scene\n<!-- s2v: sparkle=yes -->\n\nText.\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(app, ["render", str(bad), "--dry-run"])
    assert result.exit_code == 1
    assert "unknown directive key" in result.output
