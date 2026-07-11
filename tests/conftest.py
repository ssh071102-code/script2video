"""Shared fixtures: paths to the committed offline TTS fixture files."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_SCRIPT = FIXTURES / "fixture-script.md"
FIXTURE_NARRATION = FIXTURES / "narration"


@pytest.fixture
def fixture_script_path() -> Path:
    return FIXTURE_SCRIPT


@pytest.fixture
def offline_workdir(tmp_path: Path) -> Path:
    """A pipeline workdir pre-seeded with the committed narration cache.

    With every scene of the fixture script already cached, the pipeline
    never touches the network -- this is what keeps the e2e suite offline.
    """
    workdir = tmp_path / "workdir"
    tts_dir = workdir / "tts"
    tts_dir.mkdir(parents=True)
    for file in FIXTURE_NARRATION.iterdir():
        if file.suffix in (".mp3", ".json"):
            shutil.copy(file, tts_dir / file.name)
    return workdir
