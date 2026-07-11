"""Markdown script parsing.

The input format is plain markdown with a small amount of structure:

    ---
    title: My Video            # optional front matter
    voice: en-US-AriaNeural
    palette: midnight
    ---

    ## Scene title
    <!-- s2v: palette=ember motion=pan-left -->

    Narration paragraph. Everything until the next `##` heading is read
    aloud by the TTS voice.

Front matter keys: ``title``, ``voice``, ``palette``.
Scene directive keys (inside an ``<!-- s2v: ... -->`` comment):

    palette=<name>         backdrop palette for this scene
    image=<relative path>  use a supplied image instead of a generated card
    motion=<preset>        ken burns preset: zoom-in | zoom-out |
                           pan-left | pan-right (default: cycles by index)

Parsing is strict: unknown keys, unknown palettes, empty narration and
missing image files raise :class:`ScriptError` with a line number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ScriptError
from .palettes import DEFAULT_PALETTE, PALETTES, palette_names

MOTION_PRESETS = ("zoom-in", "zoom-out", "pan-left", "pan-right")
_FRONT_MATTER_KEYS = ("title", "voice", "palette")
_DIRECTIVE_KEYS = ("palette", "image", "motion")

_HEADING_RE = re.compile(r"^##(?!#)\s*(?P<title>.*?)\s*$")
_DIRECTIVE_RE = re.compile(r"^<!--\s*s2v:\s*(?P<body>.*?)\s*-->\s*$")
_KV_RE = re.compile(r"""(?P<key>[a-z-]+)=(?P<value>"[^"]*"|\S+)""")

DEFAULT_VOICE = "en-US-AriaNeural"


@dataclass
class Scene:
    """One scene: a title card plus a block of narration."""

    index: int
    title: str
    narration: str
    palette: str
    motion: str
    image: Path | None = None
    heading_line: int = 0


@dataclass
class Script:
    """A parsed markdown script."""

    title: str
    voice: str
    default_palette: str
    scenes: list[Scene] = field(default_factory=list)


def _parse_front_matter(
    lines: list[str],
) -> tuple[dict[str, str], int]:
    """Return (front matter dict, index of first body line)."""
    if not lines or lines[0].strip() != "---":
        return {}, 0
    meta: dict[str, str] = {}
    for i, raw in enumerate(lines[1:], start=1):
        line = raw.strip()
        if line == "---":
            return meta, i + 1
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ScriptError(
                f"front matter line is not 'key: value': {line!r}", line=i + 1
            )
        key, _, value = line.partition(":")
        key = key.strip().lower()
        if key not in _FRONT_MATTER_KEYS:
            raise ScriptError(
                f"unknown front matter key {key!r} "
                f"(known: {', '.join(_FRONT_MATTER_KEYS)})",
                line=i + 1,
            )
        meta[key] = value.strip()
    raise ScriptError("front matter opened with '---' but never closed", line=1)


def _parse_directive(body: str, line_no: int) -> dict[str, str]:
    directive: dict[str, str] = {}
    pos = 0
    for match in _KV_RE.finditer(body):
        if body[pos : match.start()].strip():
            raise ScriptError(
                f"malformed directive fragment {body[pos:match.start()].strip()!r} "
                "(expected key=value pairs)",
                line=line_no,
            )
        key = match.group("key")
        value = match.group("value").strip('"')
        if key not in _DIRECTIVE_KEYS:
            raise ScriptError(
                f"unknown directive key {key!r} "
                f"(known: {', '.join(_DIRECTIVE_KEYS)})",
                line=line_no,
            )
        if key in directive:
            raise ScriptError(f"duplicate directive key {key!r}", line=line_no)
        directive[key] = value
        pos = match.end()
    if body[pos:].strip() or not directive:
        raise ScriptError(
            f"malformed directive body {body!r} (expected key=value pairs)",
            line=line_no,
        )
    return directive


def _check_palette(name: str, line_no: int) -> str:
    if name not in PALETTES:
        raise ScriptError(
            f"unknown palette {name!r} (known: {', '.join(palette_names())})",
            line=line_no,
        )
    return name


def parse_script(path: Path | str) -> Script:
    """Parse a markdown script file into a :class:`Script`."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    return parse_script_text(text, base_dir=path.parent)


def parse_script_text(text: str, base_dir: Path | None = None) -> Script:
    """Parse markdown script *text*.

    ``base_dir`` is the directory used to resolve relative ``image=``
    directive paths; when ``None`` image existence is not checked against
    the filesystem (paths are still recorded).
    """
    lines = text.splitlines()
    meta, body_start = _parse_front_matter(lines)

    default_palette = meta.get("palette", DEFAULT_PALETTE)
    _check_palette(default_palette, line_no=1)

    script = Script(
        title=meta.get("title", ""),
        voice=meta.get("voice", DEFAULT_VOICE),
        default_palette=default_palette,
    )

    current: Scene | None = None
    narration_parts: list[str] = []

    def finish_scene() -> None:
        if current is None:
            return
        narration = " ".join(" ".join(narration_parts).split())
        if not narration:
            raise ScriptError(
                f"scene {current.title!r} has no narration text",
                line=current.heading_line,
            )
        current.narration = narration
        script.scenes.append(current)

    for offset, raw in enumerate(lines[body_start:]):
        line_no = body_start + offset + 1
        line = raw.strip()

        heading = _HEADING_RE.match(line)
        if heading:
            finish_scene()
            title = heading.group("title")
            if not title:
                raise ScriptError("scene heading has no title text", line=line_no)
            index = len(script.scenes)
            current = Scene(
                index=index,
                title=title,
                narration="",
                palette=default_palette,
                motion=MOTION_PRESETS[index % len(MOTION_PRESETS)],
                heading_line=line_no,
            )
            narration_parts = []
            continue

        directive_match = _DIRECTIVE_RE.match(line)
        if directive_match:
            if current is None:
                raise ScriptError(
                    "directive found before the first scene heading", line=line_no
                )
            directive = _parse_directive(directive_match.group("body"), line_no)
            if "palette" in directive:
                current.palette = _check_palette(directive["palette"], line_no)
            if "motion" in directive:
                motion = directive["motion"]
                if motion not in MOTION_PRESETS:
                    raise ScriptError(
                        f"unknown motion preset {motion!r} "
                        f"(known: {', '.join(MOTION_PRESETS)})",
                        line=line_no,
                    )
                current.motion = motion
            if "image" in directive:
                image = Path(directive["image"])
                if base_dir is not None:
                    image = (base_dir / image).resolve()
                    if not image.is_file():
                        raise ScriptError(
                            f"image file not found: {directive['image']}",
                            line=line_no,
                        )
                current.image = image
            continue

        if line.startswith("#") and not line.startswith("##"):
            # A top-level `# Title` heading is allowed as a document title.
            if current is None and not script.title:
                script.title = line.lstrip("#").strip()
                continue
            raise ScriptError(
                "unexpected '#' heading inside a scene (use '##' for scenes)",
                line=line_no,
            )

        if line:
            if current is None:
                raise ScriptError(
                    "narration text found before the first '##' scene heading",
                    line=line_no,
                )
            narration_parts.append(line)

    finish_scene()

    if not script.scenes:
        raise ScriptError("script contains no '##' scene headings")
    return script
