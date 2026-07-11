"""Caption phrasing and SRT generation from word-level timings.

The TTS engine reports the exact time span of every spoken word. Captions
are built directly from those events, so they line up with the voice to
the millisecond -- there is no speech-to-text alignment step that could
drift or mishear.

Grouping words into readable cues is the interesting part. The rules,
applied greedily in order:

1. A cue never exceeds ``max_lines * max_line_chars`` characters.
2. A cue never exceeds ``max_cue_seconds`` of speech.
3. A pause longer than ``pause_split`` seconds starts a new cue
   (the voice breathed; the caption should too).
4. Sentence-final punctuation (``. ! ?``) ends the cue.

Cue text is then wrapped onto at most ``max_lines`` lines, breaking at the
space nearest the midpoint so the lines are visually balanced. Finally,
cues shorter than ``min_cue_seconds`` are extended -- but never into the
next cue's start time.

Everything in this module is pure: words in, cues out.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_SENTENCE_END = (".", "!", "?")
_CUE_GAP = 0.08  # minimum silence between two cues, seconds


@dataclass(frozen=True)
class Word:
    """One spoken word with its time span on some clock, in seconds."""

    text: str
    start: float
    end: float

    def shifted(self, offset: float) -> "Word":
        """The same word moved onto another clock (e.g. the global timeline)."""
        return Word(self.text, round(self.start + offset, 6), round(self.end + offset, 6))


@dataclass(frozen=True)
class CaptionStyle:
    """Knobs for phrase grouping. Defaults suit 720p two-line captions."""

    max_line_chars: int = 38
    max_lines: int = 2
    min_cue_seconds: float = 1.0
    max_cue_seconds: float = 5.0
    pause_split: float = 0.6


@dataclass
class Cue:
    """One caption: lines of text shown from ``start`` to ``end`` seconds."""

    start: float
    end: float
    lines: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def group_words(words: list[Word], style: CaptionStyle | None = None) -> list[Cue]:
    """Group timed words into caption cues. See module docstring for rules."""
    style = style or CaptionStyle()
    if not words:
        return []

    budget = style.max_line_chars * style.max_lines
    groups: list[list[Word]] = []
    current: list[Word] = []
    length = 0  # chars incl. separating spaces

    for word in words:
        needed = len(word.text) if not current else len(word.text) + 1
        pause = current and (word.start - current[-1].end) > style.pause_split
        over_budget = current and (length + needed) > budget
        over_time = current and (word.end - current[0].start) > style.max_cue_seconds
        if pause or over_budget or over_time:
            groups.append(current)
            current, length = [], 0
            needed = len(word.text)
        current.append(word)
        length += needed
        if word.text.endswith(_SENTENCE_END):
            groups.append(current)
            current, length = [], 0
    if current:
        groups.append(current)

    cues = [
        Cue(
            start=group[0].start,
            end=group[-1].end,
            lines=wrap_lines(
                " ".join(w.text for w in group),
                style.max_line_chars,
                style.max_lines,
            ),
        )
        for group in groups
    ]
    _enforce_min_duration(cues, style.min_cue_seconds)
    return cues


def wrap_lines(text: str, max_line_chars: int, max_lines: int) -> list[str]:
    """Wrap *text* onto at most *max_lines* balanced lines.

    A single line is used when it fits. For two-line wrapping the break is
    placed at the space nearest the midpoint that keeps both halves within
    ``max_line_chars``; longer inputs fall back to greedy fill.
    """
    if len(text) <= max_line_chars:
        return [text]
    if max_lines >= 2:
        split = _balanced_split(text, max_line_chars)
        if split is not None:
            return split
    return _greedy_wrap(text, max_line_chars, max_lines)


def _balanced_split(text: str, max_line_chars: int) -> list[str] | None:
    mid = len(text) / 2
    best: tuple[float, str, str] | None = None
    for i, ch in enumerate(text):
        if ch != " ":
            continue
        head, tail = text[:i], text[i + 1 :]
        if len(head) <= max_line_chars and len(tail) <= max_line_chars:
            distance = abs(i - mid)
            if best is None or distance < best[0]:
                best = (distance, head, tail)
    if best is None:
        return None
    return [best[1], best[2]]


def _greedy_wrap(text: str, max_line_chars: int, max_lines: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for token in text.split(" "):
        candidate = f"{current} {token}".strip()
        if current and len(candidate) > max_line_chars:
            lines.append(current)
            current = token
        else:
            current = candidate
    if current:
        lines.append(current)
    if len(lines) > max_lines:  # overflow: merge the tail rather than drop it
        lines[max_lines - 1] = " ".join(lines[max_lines - 1 :])
        del lines[max_lines:]
    return lines


def _enforce_min_duration(cues: list[Cue], min_seconds: float) -> None:
    for i, cue in enumerate(cues):
        wanted = cue.start + min_seconds
        if cue.end >= wanted:
            continue
        limit = cues[i + 1].start - _CUE_GAP if i + 1 < len(cues) else wanted
        cue.end = round(max(cue.end, min(wanted, limit)), 6)


def format_timestamp(seconds: float) -> str:
    """Format seconds as an SRT timestamp: ``HH:MM:SS,mmm``."""
    if seconds < 0:
        raise ValueError(f"timestamp must be >= 0, got {seconds}")
    total_ms = round(seconds * 1000)
    ms = total_ms % 1000
    total_s = total_ms // 1000
    return f"{total_s // 3600:02d}:{total_s % 3600 // 60:02d}:{total_s % 60:02d},{ms:03d}"


def to_srt(cues: list[Cue]) -> str:
    """Serialize cues as an SRT document (LF line endings, trailing newline)."""
    blocks = [
        f"{i}\n{format_timestamp(c.start)} --> {format_timestamp(c.end)}\n{c.text}\n"
        for i, c in enumerate(cues, start=1)
    ]
    return "\n".join(blocks)
