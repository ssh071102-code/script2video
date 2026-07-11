"""TTS cache behavior -- all offline; the network path is never exercised."""

import json
from pathlib import Path

import pytest

import script2video.tts as tts
from script2video.captions import Word
from script2video.tts import cache_key, load_cached, restore_punctuation, synthesize


def seed_cache(cache_dir: Path, text: str, voice: str) -> str:
    key = cache_key(text, voice)
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{key}.mp3").write_bytes(b"not-really-mp3")
    (cache_dir / f"{key}.json").write_text(
        json.dumps(
            {
                "voice": voice,
                "rate": "+0%",
                "text_sha256": "irrelevant-here",
                "audio_file": f"{key}.mp3",
                "duration": 2.5,
                "words": [
                    {"text": "Hello", "start": 0.05, "end": 0.4},
                    {"text": "world.", "start": 0.45, "end": 0.9},
                ],
            }
        ),
        encoding="utf-8",
    )
    return key


def test_cache_key_is_stable_and_input_sensitive() -> None:
    key = cache_key("hello", "en-US-AriaNeural")
    assert key == cache_key("hello", "en-US-AriaNeural")
    assert len(key) == 16
    assert key != cache_key("hello!", "en-US-AriaNeural")
    assert key != cache_key("hello", "en-GB-SoniaNeural")
    assert key != cache_key("hello", "en-US-AriaNeural", rate="+10%")


def test_load_cached_roundtrip(tmp_path: Path) -> None:
    seed_cache(tmp_path, "Hello world.", "en-US-AriaNeural")
    narration = load_cached("Hello world.", "en-US-AriaNeural", tmp_path)
    assert narration is not None
    assert narration.duration == 2.5
    assert [w.text for w in narration.words] == ["Hello", "world."]
    assert narration.words[0].start == 0.05


def test_load_cached_misses_on_absent_files(tmp_path: Path) -> None:
    assert load_cached("nothing here", "en-US-AriaNeural", tmp_path) is None


def test_synthesize_uses_cache_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def explode(*args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("network path must not be hit on cache hit")

    monkeypatch.setattr(tts, "_stream", explode)
    seed_cache(tmp_path, "Hello world.", "en-US-AriaNeural")
    narration = synthesize("Hello world.", "en-US-AriaNeural", tmp_path)
    assert narration.duration == 2.5


class TestRestorePunctuation:
    def test_reattaches_punctuation_from_script(self) -> None:
        words = [Word("Hello", 0.0, 0.3), Word("world", 0.4, 0.8)]
        restored = restore_punctuation("Hello, world.", words)
        assert [w.text for w in restored] == ["Hello,", "world."]
        assert restored[1].start == 0.4  # timings untouched

    def test_merges_split_hyphenated_token(self) -> None:
        words = [
            Word("Retrieval", 0.0, 0.5),
            Word("augmented", 0.5, 1.0),
            Word("generation", 1.1, 1.7),
        ]
        restored = restore_punctuation("Retrieval-augmented generation,", words)
        assert [w.text for w in restored] == [
            "Retrieval-augmented",
            "generation,",
        ]
        assert (restored[0].start, restored[0].end) == (0.0, 1.0)  # merged span

    def test_case_differences_still_match(self) -> None:
        words = [Word("RAG", 0.0, 0.4)]
        assert restore_punctuation("rag,", words)[0].text == "rag,"

    def test_mismatch_falls_back_to_event_text(self) -> None:
        words = [Word("four", 0.0, 0.4), Word("plus", 0.5, 0.9)]
        restored = restore_punctuation("4 plus", words)
        assert [w.text for w in restored] == ["four", "plus"]

    def test_more_events_than_tokens_keeps_everything(self) -> None:
        words = [Word("a", 0.0, 0.1), Word("b", 0.2, 0.3)]
        restored = restore_punctuation("a", words)
        assert [w.text for w in restored] == ["a", "b"]
