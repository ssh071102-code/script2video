"""Running and probing media with the bundled ffmpeg binary.

imageio-ffmpeg ships a static ffmpeg build inside its wheel, so the
pipeline needs no system-wide install. It does *not* ship ffprobe, so
:func:`probe` parses ffmpeg's own stream-info output instead -- the
``Duration:`` and ``Stream #`` header lines come from the same demuxer
ffprobe would use.

All subprocess output is captured; failures surface as
:class:`MediaError` with the tail of stderr attached.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .errors import MediaError

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d\d):(\d\d(?:\.\d+)?)")
_VIDEO_RE = re.compile(r"Stream #.*?: Video: (?P<codec>\w+).*?(?P<w>\d{2,5})x(?P<h>\d{2,5})")
_AUDIO_RE = re.compile(r"Stream #.*?: Audio: (?P<codec>\w+).*?(?P<hz>\d+) Hz")
_STDERR_TAIL = 800


def get_ffmpeg_exe() -> str:
    """Path to the ffmpeg binary bundled by imageio-ffmpeg."""
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


@dataclass(frozen=True)
class VideoStream:
    codec: str
    width: int
    height: int


@dataclass(frozen=True)
class AudioStream:
    codec: str
    sample_rate: int


@dataclass(frozen=True)
class ProbeResult:
    duration: float
    video: VideoStream | None = None
    audio: AudioStream | None = None
    decode_errors: tuple[str, ...] = field(default=())

    @property
    def ok(self) -> bool:
        return self.duration > 0 and not self.decode_errors


def run_ffmpeg(args: list[str], cwd: Path, timeout: float = 600.0) -> str:
    """Run ffmpeg with *args* (exe not included) in *cwd*; return stderr.

    ffmpeg is executed with ``cwd`` set to the working directory so every
    path in the argv can stay relative -- see filtergraph.py for why.
    """
    cmd = [get_ffmpeg_exe(), *args]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"ffmpeg timed out after {timeout:.0f}s") from exc
    if result.returncode != 0:
        raise MediaError(
            f"ffmpeg exited with code {result.returncode}:\n"
            f"{result.stderr[-_STDERR_TAIL:]}"
        )
    return result.stderr


def probe(path: Path, *, decode: bool = False) -> ProbeResult:
    """Read duration and stream layout of a media file.

    With ``decode=True`` the file is fully decoded to the null muxer and
    any decoder errors are attached -- a stronger validity check used by
    the test suite (catches truncated files that still have clean headers).
    """
    path = Path(path)
    if not path.is_file():
        raise MediaError(f"file not found: {path}")

    args = [get_ffmpeg_exe(), "-hide_banner", "-i", str(path)]
    if decode:
        args += ["-v", "error", "-f", "null", "-"]
        # For decode mode, stream info must come from a separate header pass.
        header = subprocess.run(
            [get_ffmpeg_exe(), "-hide_banner", "-i", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).stderr
        decoded = subprocess.run(
            args, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        errors = tuple(line for line in decoded.stderr.splitlines() if line.strip())
        if decoded.returncode != 0 and not errors:
            errors = (f"ffmpeg decode pass exited with {decoded.returncode}",)
        return _parse_header(header, path, errors)

    # Header-only pass: ffmpeg exits non-zero ("no output specified") by
    # design; the stream info on stderr is what we want.
    header = subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", errors="replace"
    ).stderr
    return _parse_header(header, path, ())


def _parse_header(stderr: str, path: Path, errors: tuple[str, ...]) -> ProbeResult:
    duration_match = _DURATION_RE.search(stderr)
    if not duration_match:
        raise MediaError(
            f"could not read duration of {path.name}:\n{stderr[-_STDERR_TAIL:]}"
        )
    hours, minutes, seconds = duration_match.groups()
    duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    video = None
    video_match = _VIDEO_RE.search(stderr)
    if video_match:
        video = VideoStream(
            codec=video_match.group("codec"),
            width=int(video_match.group("w")),
            height=int(video_match.group("h")),
        )
    audio = None
    audio_match = _AUDIO_RE.search(stderr)
    if audio_match:
        audio = AudioStream(
            codec=audio_match.group("codec"),
            sample_rate=int(audio_match.group("hz")),
        )
    return ProbeResult(
        duration=round(duration, 3), video=video, audio=audio, decode_errors=errors
    )
