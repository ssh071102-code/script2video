"""Regenerate the committed TTS fixtures (requires network).

The test suite runs offline against real edge-tts output stored in
tests/fixtures/narration/. When the fixture script changes, re-run:

    python scripts/refresh_fixtures.py

and commit the resulting mp3/json pairs.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from script2video.script import parse_script  # noqa: E402
from script2video.tts import synthesize  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def main() -> None:
    script = parse_script(FIXTURES / "fixture-script.md")
    out_dir = FIXTURES / "narration"
    total = 0
    for scene in script.scenes:
        narration = synthesize(scene.narration, script.voice, out_dir)
        size = narration.audio_path.stat().st_size
        total += size
        print(
            f"scene {scene.index}: {narration.audio_path.name} "
            f"({size} bytes, {narration.duration:.2f}s, "
            f"{len(narration.words)} words)"
        )
    print(f"total audio: {total} bytes -> {out_dir.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
