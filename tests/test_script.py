"""Script parser: happy path and every documented failure mode."""

from pathlib import Path

import pytest
from PIL import Image

from script2video.errors import ScriptError
from script2video.script import parse_script, parse_script_text

GOOD = """\
---
title: Test Video
voice: en-GB-SoniaNeural
palette: slate
---

## First Scene

Hello there.

## Second Scene
<!-- s2v: palette=kelp motion=pan-left -->

Line one of narration.
Line two of narration.
"""


def test_parses_front_matter_and_scenes() -> None:
    script = parse_script_text(GOOD)
    assert script.title == "Test Video"
    assert script.voice == "en-GB-SoniaNeural"
    assert script.default_palette == "slate"
    assert [s.title for s in script.scenes] == ["First Scene", "Second Scene"]


def test_narration_paragraphs_are_joined() -> None:
    script = parse_script_text(GOOD)
    assert script.scenes[1].narration == "Line one of narration. Line two of narration."


def test_directive_overrides_palette_and_motion() -> None:
    script = parse_script_text(GOOD)
    first, second = script.scenes
    assert (first.palette, second.palette) == ("slate", "kelp")
    assert first.motion == "zoom-in"  # index cycle default
    assert second.motion == "pan-left"  # explicit override


def test_front_matter_is_optional() -> None:
    script = parse_script_text("## Only Scene\n\nWords here.\n")
    assert script.voice == "en-US-AriaNeural"
    assert script.default_palette == "midnight"
    assert len(script.scenes) == 1


def test_document_title_heading() -> None:
    script = parse_script_text("# Doc Title\n\n## Scene\n\nText.\n")
    assert script.title == "Doc Title"


def test_image_directive_resolves_against_script_dir(tmp_path: Path) -> None:
    Image.new("RGB", (32, 32), (10, 20, 30)).save(tmp_path / "bg.png")
    (tmp_path / "s.md").write_text(
        "## Scene\n<!-- s2v: image=bg.png -->\n\nText.\n", encoding="utf-8"
    )
    script = parse_script(tmp_path / "s.md")
    assert script.scenes[0].image == (tmp_path / "bg.png").resolve()


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("just prose, no headings", "before the first"),
        ("---\ntitle: x\n", "never closed"),
        ("---\nbogus: x\n---\n## S\n\nT.\n", "unknown front matter key"),
        ("---\npalette: neon\n---\n## S\n\nT.\n", "unknown palette"),
        ("## S\n<!-- s2v: palette=neon -->\n\nT.\n", "unknown palette"),
        ("## S\n<!-- s2v: sparkle=yes -->\n\nT.\n", "unknown directive key"),
        ("## S\n<!-- s2v: palette -->\n\nT.\n", "malformed directive"),
        ("## S\n<!-- s2v: motion=wobble -->\n\nT.\n", "unknown motion preset"),
        ("## S\n<!-- s2v: image=missing.png -->\n\nT.\n", "image file not found"),
        ("<!-- s2v: palette=kelp -->\n## S\n\nT.\n", "before the first scene"),
        ("## S\n\n## T\n\nWords.\n", "no narration"),
        ("##\n\nT.\n", "no title text"),
        ("## S\n\nT.\n\n# Late Top Heading\n\nMore.\n", "unexpected '#' heading"),
        ("", "no '##' scene headings"),
    ],
)
def test_malformed_scripts_raise(text: str, match: str, tmp_path: Path) -> None:
    (tmp_path / "bad.md").write_text(text, encoding="utf-8")
    with pytest.raises(ScriptError, match=match):
        parse_script(tmp_path / "bad.md")


def test_error_carries_line_number() -> None:
    with pytest.raises(ScriptError) as excinfo:
        parse_script_text("## S\n<!-- s2v: sparkle=yes -->\n\nT.\n")
    assert excinfo.value.line == 2
    assert "line 2" in str(excinfo.value)
