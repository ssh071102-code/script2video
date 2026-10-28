# script2video

[![CI](https://github.com/ssh071102-code/script2video/actions/workflows/ci.yml/badge.svg)](https://github.com/ssh071102-code/script2video/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

script2video turns a markdown script into a narrated, captioned mp4 with a
single command: edge-tts narration, captions timed from the TTS word
boundaries, and an ffmpeg encode built from a pure function.

![Seven seconds of the sample render: scene 1 crossfades into scene 2 with burned-in captions](docs/demo.gif)

The GIF above is a 7-second excerpt (640 px, 10 fps) of
[docs/demo.mp4](docs/demo.mp4), an 83-second explainer rendered by this
pipeline from [examples/demo-script.md](examples/demo-script.md). Every
visual is generated in code (palette gradients, PIL typography, film grain,
Ken Burns motion). There is no stock footage or downloaded media.

```console
$ pip install git+https://github.com/ssh071102-code/script2video
$ script2video render examples/demo-script.md -o docs/demo.mp4 --crf 26
script2video 0.1.0
script : examples/demo-script.md (5 scenes, voice en-US-AriaNeural)
[1/4] narration  5 synthesized, 0 cached (188 word boundaries) [8.8s]
[2/4] captions   21 cues -> captions.srt [0.0s]
[3/4] backdrops  5 cards at 2560x1440 (2x supersampled) [2.8s]
[4/4] assembly   xfade chain + caption burn-in, crf 26 [8.1s]

scene  start      narration  visual   title
  1       0.00s    17.30s       18.92s   Frozen Knowledge
  2      18.52s    13.03s       14.64s   Retrieval in One Sentence
  3      32.76s    16.20s       17.80s   Chunk, Embed, Store
  4      50.16s    15.22s       16.84s   The Grounded Prompt
  5      66.60s    15.07s       16.68s   Why It Matters
total    83.28s

output : docs/demo.mp4 (3.02 MiB, 83.28s, h264 1280x720 + aac 48000 Hz)
```

This is the assembly and timing layer of a video production system. It
takes a script and handles the steps from text on disk to a valid mp4:
narration, captions, backdrops, transitions and the encode.

## Pipeline

```mermaid
flowchart LR
    A[markdown script] --> B[parser<br/>scenes + directives]
    B --> C[edge-tts<br/>audio + word boundaries]
    C --> D[timeline<br/>frame-exact global clock]
    D --> E[captions<br/>phrase grouping -> SRT]
    B --> F[backdrops<br/>PIL gradient + typography]
    D --> G[filtergraph<br/>deterministic ffmpeg argv]
    E --> G
    F --> G
    G --> H[mp4<br/>xfade + burn-in + narration]
```

- **TTS**: [edge-tts](https://github.com/rany2/edge-tts) (free, no API key).
  The service streams `WordBoundary` events alongside the audio; both are
  persisted per scene (`.mp3` + `.json`) and cached by a hash of
  `voice | rate | text`, so unchanged scenes are never re-synthesized.
- **Captions**: built directly from those word boundaries, grouped into
  readable cues by character budget, speech pauses, sentence ends, and a
  max cue duration, then balanced onto two lines. Punctuation is restored
  from the script text (boundary events carry bare words). When the voice
  reads a token differently, for example "2026" as "twenty twenty six",
  the restore step keeps the spoken words and re-aligns on the next
  matching words.
- **Visuals**: each scene gets a generated 2x-supersampled card; ffmpeg's
  `zoompan` adds slow zoom/pan (four presets, cycled per scene), `xfade`
  crossfades scenes, and the `subtitles` filter burns the SRT.
- **Assembly**: ffmpeg ships inside the
  [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) wheel, so
  no system install is needed. The full argv is constructed by a pure module.

## Commands

```console
$ script2video render script.md -o out/video.mp4    # full render
$ script2video render script.md --dry-run           # plan only: timings + filtergraph
$ script2video captions script.md -o out/video.srt  # SRT only, same clock as render
```

`--dry-run` prints the scene table, crossfade offsets, and the exact
filtergraph chains without touching ffmpeg. Scenes already in the
narration cache show real durations; uncached scenes show a
words-per-second estimate marked `(est)`.

`captions` emits the same cue times a full render would use, so the SRT
works as a sidecar for a previously rendered video.

## Script format

```markdown
---
title: How Retrieval-Augmented Generation Works
voice: en-US-AriaNeural
palette: midnight
---

## Frozen Knowledge

Narration for the first scene. Every paragraph until the next `##`
heading is spoken.

## Retrieval in One Sentence
<!-- s2v: palette=aurora motion=pan-left -->

More narration.
```

- **Front matter** (optional): `title`, `voice` (any edge-tts voice),
  `palette` (default backdrop palette).
- **`## Heading`** starts a scene; the heading text becomes the card title.
- **Directives** live in an `<!-- s2v: key=value ... -->` comment inside
  the scene:

| key       | values                                              | effect                          |
| --------- | --------------------------------------------------- | ------------------------------- |
| `palette` | `midnight` `ember` `kelp` `slate` `aurora` `dawn`   | backdrop colors for this scene  |
| `motion`  | `zoom-in` `zoom-out` `pan-left` `pan-right`         | Ken Burns preset (else cycled)  |
| `image`   | path relative to the script                         | your image instead of a card    |

Parsing is strict: unknown keys, unknown palettes, empty narration, and
missing image files fail with a line number instead of rendering something
half right.

## How timing works

Scenes crossfade, so the global timeline is shorter than the sum of scene
durations. Captions, audio delays, xfade offsets and the final `-t` all
have to agree on the same arithmetic. `timeline.py` computes it once:

```
visual[i]          = pad_head + ceil_frame(narration[i]) + pad_tail   (all in whole frames)
video_start[i]     = sum(visual[j] for j < i) - i * fade
narration_start[i] = video_start[i] + pad_head
total              = sum(visual) - (n - 1) * fade
```

`build_timeline` checks two invariants and raises if either fails.
Everything is quantized to whole frames first, because an xfade offset
that misses a frame boundary makes a visible seam. Both pads, after
rounding to frames, must be >= the rounded fade, and narration length is
rounded up to the next frame, so the silence after each voice is never
shorter than the fade. Word timings are shifted by `narration_start[i]`
onto the global clock before cue grouping, so a caption never spans two
scenes.

## Design notes

**Why word boundaries instead of STT alignment?** The usual way to caption
synthetic narration is to render audio, then run speech-to-text or forced
alignment over it. That adds a model dependency, drifts on numbers and
names, and can mishear text you already have. The TTS engine reports
when it speaks each word; recording the `WordBoundary` events gives
millisecond cues without a second model or a transcription step. The
trade-off is that caption timing is only as good as the TTS metadata,
which is acceptable when the narration is synthetic anyway.

**Why a pure filtergraph builder?** `filtergraph.py` maps
`(timeline, filenames, settings) -> argv` with no I/O, no randomness, no
clocks. The test suite asserts the *entire* ffmpeg command for known
inputs, so a regression in assembly logic fails a string comparison
before it reaches a rendered video. ffmpeg also runs with `cwd` set to the
working directory and only sees bare relative filenames. That avoids
Windows path quoting inside filter strings and keeps the argv
byte-identical across machines.

**Why generated backdrops?** With no third-party media in the repository
there are no licensing questions, and the code stays focused on assembly. Cards are rendered at 2x output resolution so `zoompan`
only ever scales down. Titles use a system font chain (Segoe UI / Arial /
DejaVu / Liberation, then Pillow's built-in fallback); no font files are
bundled, and caption burn-in falls back through fontconfig the same way.

## Options

| flag                | default          | notes                             |
| ------------------- | ---------------- | --------------------------------- |
| `-o, --output`      | `out/video.mp4`  | output path (`render`)            |
| `--voice`           | script / Aria    | any edge-tts voice name           |
| `--width, --height` | 1280 x 720       | output resolution                 |
| `--fps`             | 25               | frame rate (timing quantum)       |
| `--crf`             | 23               | x264 quality; demo uses 26        |
| `--fade`            | 0.4              | crossfade seconds                 |
| `--burn/--no-burn`  | burn             | burn captions into the video      |
| `--workdir`         | `.script2video`  | cache + intermediates             |
| `--dry-run`         | off              | print the plan, render nothing    |

## Testing

```console
$ pip install -e ".[dev]"
$ pytest -q
101 passed
```

The suite is fully offline, including an end-to-end test that assembles a
real mp4 from committed fixtures and probes it (stream layout, duration
against the computed timeline, full decode with zero errors). The fixtures
under `tests/fixtures/narration/` are genuine edge-tts output (~47 KB);
regenerate them with `python scripts/refresh_fixtures.py` when the fixture
script changes. The parser, timeline math, cue grouping, SRT formatting
and argv construction are pure functions tested with known-answer cases.

## Limitations

- **TTS needs the network.** edge-tts calls Microsoft's endpoint; there is
  no offline voice. Narration is cached aggressively, and everything
  downstream of the cache runs offline.
- **Synthetic voices sound synthetic.** Fine for explainers and drafts.
- **`--dry-run` estimates run short.** Uncached scenes are estimated at
  2.9 words per second. For the demo script that gives 64.8s of narration
  against 76.8s in the synthesized audio, about 16% short.
- **This is the assembly layer.** Creative direction, model-generated
  footage, music and mixing are out of scope. This layer covers timing,
  captions and a reproducible encode.

## Related

[continuity-showrunner](https://github.com/ssh071102-code/continuity-showrunner)
produces generative shots; script2video does the deterministic narration,
caption and assembly step.

## License

MIT. Copyright (c) 2026 Laurin Lin.
