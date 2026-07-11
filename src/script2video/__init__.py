"""script2video: turn a markdown script into a narrated, captioned video.

The pipeline is a chain of small, mostly pure modules:

    script.py      markdown script -> Scene objects
    tts.py         narration text -> audio + word boundaries (edge-tts)
    timeline.py    narration durations -> frame-exact global timeline
    captions.py    word boundaries -> phrase-grouped cues -> SRT
    palettes.py    named color palettes for generated backdrops
    backdrop.py    palette + title -> scene backdrop image (PIL)
    filtergraph.py timeline + files -> deterministic ffmpeg argv
    media.py       run ffmpeg / probe media (bundled binary)
    pipeline.py    orchestration of the above
"""

__version__ = "0.1.0"
