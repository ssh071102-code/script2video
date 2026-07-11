"""Neural narration via edge-tts, with word boundaries captured.

Microsoft Edge's online TTS service streams two things: audio chunks and
``WordBoundary`` metadata events carrying the exact offset and duration of
every spoken word (in 100-nanosecond ticks). We persist both:

    <cache_key>.mp3    the narration audio
    <cache_key>.json   voice, rate, measured duration, word timings

The cache key is a hash of ``voice | rate | text``, so re-renders and the
``captions`` command reuse audio without hitting the network, and the test
suite runs fully offline from committed fixture files.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .captions import Word
from .errors import NarrationError

_TICKS_PER_SECOND = 10_000_000
DEFAULT_RATE = "+0%"


def restore_punctuation(text: str, words: list[Word]) -> list[Word]:
    """Map boundary words back onto the script's own tokens.

    Edge's ``WordBoundary`` events carry bare words -- no commas, periods
    or hyphens -- but the captions should read like the script. Walk the
    script tokens and the boundary events together: when a token matches
    (ignoring case and punctuation) emit the *token* with the boundary's
    timing; when the service split a hyphenated token into several events,
    merge their time spans. Unmatched events fall back to their own text
    so a surprise never drops a caption word.
    """

    def norm(s: str) -> str:
        return "".join(ch for ch in s.lower() if ch.isalnum())

    tokens = text.split()
    out: list[Word] = []
    t = 0
    i = 0
    while i < len(words):
        word = words[i]
        if t >= len(tokens):
            out.append(word)
            i += 1
            continue
        token_norm = norm(tokens[t])
        if norm(word.text) == token_norm:
            out.append(Word(tokens[t], word.start, word.end))
            t += 1
            i += 1
            continue
        # The service may split one script token (e.g. "Retrieval-augmented")
        # into several boundary events; merge while they prefix-match.
        merged = norm(word.text)
        j = i + 1
        while j < len(words) and token_norm.startswith(merged) and merged != token_norm:
            merged += norm(words[j].text)
            j += 1
        if merged == token_norm:
            out.append(Word(tokens[t], word.start, words[j - 1].end))
            t += 1
            i = j
            continue
        out.append(word)  # give up on this event, keep clocks moving
        t += 1
        i += 1
    return out


@dataclass(frozen=True)
class Narration:
    """A synthesized (or cache-loaded) narration clip."""

    audio_path: Path
    boundary_path: Path
    voice: str
    rate: str
    duration: float
    words: tuple[Word, ...]


def cache_key(text: str, voice: str, rate: str = DEFAULT_RATE) -> str:
    """Stable identifier for one (voice, rate, text) synthesis request."""
    digest = hashlib.sha256(f"{voice}|{rate}|{text}".encode("utf-8")).hexdigest()
    return digest[:16]


def synthesize(
    text: str,
    voice: str,
    cache_dir: Path,
    *,
    rate: str = DEFAULT_RATE,
) -> Narration:
    """Return narration for *text*, from cache if present, else via network.

    Raises :class:`NarrationError` when synthesis fails (edge-tts needs
    network access) or when the service returns no word boundaries.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = cache_key(text, voice, rate)
    audio_path = cache_dir / f"{key}.mp3"
    boundary_path = cache_dir / f"{key}.json"

    cached = load_cached(text, voice, cache_dir, rate=rate)
    if cached is not None:
        return cached

    try:
        audio, raw_words = asyncio.run(_stream(text, voice, rate))
    except NarrationError:
        raise
    except Exception as exc:  # aiohttp/edge-tts network and protocol errors
        raise NarrationError(
            f"TTS synthesis failed ({type(exc).__name__}: {exc}). "
            "edge-tts requires network access to Microsoft's TTS endpoint."
        ) from exc

    if not audio:
        raise NarrationError("TTS service returned no audio")
    if not raw_words:
        raise NarrationError("TTS service returned no word boundaries")

    audio_path.write_bytes(audio)

    # Measure the real container duration with the bundled ffmpeg; the last
    # word boundary undershoots it (trailing silence), and the timeline
    # needs the true audio length.
    from .media import probe  # local import: media pulls in imageio-ffmpeg

    duration = probe(audio_path).duration
    words = restore_punctuation(
        text,
        [
            Word(
                text=w["text"],
                start=round(w["offset"] / _TICKS_PER_SECOND, 6),
                end=round((w["offset"] + w["duration"]) / _TICKS_PER_SECOND, 6),
            )
            for w in raw_words
        ],
    )
    boundary_path.write_text(
        json.dumps(
            {
                "voice": voice,
                "rate": rate,
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "audio_file": audio_path.name,
                "duration": duration,
                "words": [
                    {"text": w.text, "start": w.start, "end": w.end} for w in words
                ],
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    return Narration(
        audio_path=audio_path,
        boundary_path=boundary_path,
        voice=voice,
        rate=rate,
        duration=duration,
        words=tuple(words),
    )


def load_cached(
    text: str,
    voice: str,
    cache_dir: Path,
    *,
    rate: str = DEFAULT_RATE,
) -> Narration | None:
    """Load a previously synthesized narration, or ``None`` on cache miss."""
    key = cache_key(text, voice, rate)
    audio_path = cache_dir / f"{key}.mp3"
    boundary_path = cache_dir / f"{key}.json"
    if not (audio_path.is_file() and boundary_path.is_file()):
        return None
    data = json.loads(boundary_path.read_text(encoding="utf-8"))
    return Narration(
        audio_path=audio_path,
        boundary_path=boundary_path,
        voice=data["voice"],
        rate=data["rate"],
        duration=float(data["duration"]),
        words=tuple(Word(w["text"], w["start"], w["end"]) for w in data["words"]),
    )


async def _stream(text: str, voice: str, rate: str) -> tuple[bytes, list[dict]]:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    audio = bytearray()
    words: list[dict] = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            words.append(
                {
                    "text": str(chunk["text"]),
                    "offset": int(chunk["offset"]),
                    "duration": int(chunk["duration"]),
                }
            )
    return bytes(audio), words
