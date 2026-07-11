"""Known-answer tests for phrase grouping, wrapping, and SRT output."""

import pytest

from script2video.captions import (
    CaptionStyle,
    Cue,
    Word,
    format_timestamp,
    group_words,
    to_srt,
    wrap_lines,
)


def words_from(spec: str, start: float = 0.0, per_word: float = 0.3) -> list[Word]:
    """Build evenly spaced words: 'a b c' -> [a@0.0, b@0.3, c@0.6]."""
    out = []
    t = start
    for token in spec.split():
        out.append(Word(token, round(t, 6), round(t + per_word, 6)))
        t += per_word
    return out


class TestGrouping:
    def test_sentence_end_starts_new_cue(self) -> None:
        words = words_from("It works. Truly it does.")
        cues = group_words(words)
        assert [c.text for c in cues] == ["It works.", "Truly it does."]

    def test_long_pause_starts_new_cue(self) -> None:
        words = [
            Word("before", 0.0, 0.4),
            Word("pause", 1.5, 1.9),  # 1.1s gap > 0.6s threshold
        ]
        cues = group_words(words)
        assert len(cues) == 2
        assert cues[1].start == 1.5

    def test_char_budget_splits_cue(self) -> None:
        style = CaptionStyle(max_line_chars=10, max_lines=2, min_cue_seconds=0.0)
        words = words_from("aaaa bbbb cccc dddd eeee ffff")
        cues = group_words(words, style)
        assert all(len(c.text.replace("\n", " ")) <= 20 for c in cues)
        assert len(cues) == 2

    def test_max_duration_splits_cue(self) -> None:
        style = CaptionStyle(max_cue_seconds=2.0, min_cue_seconds=0.0)
        words = words_from("one two three four five six seven eight", per_word=0.5)
        cues = group_words(words, style)
        assert len(cues) > 1
        for cue in cues:
            assert cue.end - cue.start <= 2.0 + 1e-9

    def test_short_cue_extended_to_min_duration(self) -> None:
        words = [Word("Blink.", 0.0, 0.3), Word("Longer", 4.0, 4.4)]
        cues = group_words(words, CaptionStyle(min_cue_seconds=1.0))
        assert cues[0].end == 1.0

    def test_extension_never_reaches_next_cue(self) -> None:
        words = [Word("Blink.", 0.0, 0.3), Word("Next", 0.5, 0.9)]
        cues = group_words(words, CaptionStyle(min_cue_seconds=5.0))
        assert cues[0].end <= cues[1].start - 0.08 + 1e-9

    def test_empty_input(self) -> None:
        assert group_words([]) == []


class TestWrapping:
    def test_single_line_when_it_fits(self) -> None:
        assert wrap_lines("short text", 38, 2) == ["short text"]

    def test_balanced_two_line_break(self) -> None:
        text = "the quick brown fox jumps over the lazy dog"  # 43 chars
        assert wrap_lines(text, 25, 2) == [
            "the quick brown fox",
            "jumps over the lazy dog",
        ]

    def test_greedy_fallback_merges_overflow(self) -> None:
        text = "alpha beta gamma delta epsilon zeta eta theta"
        lines = wrap_lines(text, 12, 2)
        assert len(lines) == 2
        assert " ".join(lines) == text  # nothing dropped


class TestTimestamps:
    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [
            (0.0, "00:00:00,000"),
            (1.5, "00:00:01,500"),
            (59.999, "00:00:59,999"),
            (61.0, "00:01:01,000"),
            (3661.25, "01:01:01,250"),
            (0.0004, "00:00:00,000"),  # rounds down
            (0.0006, "00:00:00,001"),  # rounds up
        ],
    )
    def test_format(self, seconds: float, expected: str) -> None:
        assert format_timestamp(seconds) == expected

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValueError):
            format_timestamp(-0.1)


class TestSrt:
    def test_exact_document(self) -> None:
        cues = [
            Cue(start=0.6, end=2.84, lines=["It works."]),
            Cue(start=3.1, end=5.0, lines=["Two lines", "of caption text."]),
        ]
        assert to_srt(cues) == (
            "1\n"
            "00:00:00,600 --> 00:00:02,840\n"
            "It works.\n"
            "\n"
            "2\n"
            "00:00:03,100 --> 00:00:05,000\n"
            "Two lines\nof caption text.\n"
        )

    def test_empty(self) -> None:
        assert to_srt([]) == ""
