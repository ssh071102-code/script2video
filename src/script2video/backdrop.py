"""Program-generated scene backdrops (PIL).

Every backdrop is synthesized from a :class:`~script2video.palettes.Palette`:
a corner-to-corner multi-stop gradient, two soft glow fields (screen-
blended), one thin geometric ring, film grain, a vignette, and the scene
typography. No stock imagery, no downloaded assets.

Cards are rendered at 2x the output resolution so the ffmpeg zoompan
(Ken Burns) stage always scales *down*, keeping edges crisp.

Determinism: layout variants and grain are seeded by scene index, so the
same script renders the same frames on every machine.

Fonts: titles use the first available font from a system-safe chain
(Segoe UI / Arial on Windows, DejaVu / Liberation on Linux, Arial on
macOS) and fall back to Pillow's built-in font. No font files ship with
this repository.
"""

from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from .palettes import Palette

SUPERSAMPLE = 2

_BOLD_FONTS = (
    "segoeuib.ttf",
    "arialbd.ttf",
    "DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)
_REGULAR_FONTS = (
    "segoeui.ttf",
    "arial.ttf",
    "DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
)

# Normalized (x, y) layout variants, cycled by scene index: two glow
# centers and one ring center each.
_LAYOUTS = (
    ((0.82, 0.16), (0.12, 0.92), (0.74, 0.70)),
    ((0.18, 0.14), (0.86, 0.82), (0.24, 0.34)),
    ((0.52, 0.04), (0.92, 0.88), (0.86, 0.26)),
    ((0.10, 0.62), (0.76, 0.08), (0.62, 0.86)),
)


def _load_font(candidates: tuple[str, ...], size: int) -> ImageFont.FreeTypeFont:
    for name in candidates:
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)  # type: ignore[return-value]


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def _gradient_color(stops: tuple[tuple[int, int, int], ...], t: float) -> tuple[int, int, int]:
    if len(stops) == 1:
        return stops[0]
    t = min(max(t, 0.0), 1.0)
    scaled = t * (len(stops) - 1)
    i = min(int(scaled), len(stops) - 2)
    return _lerp(stops[i], stops[i + 1], scaled - i)


def _base_gradient(size: tuple[int, int], palette: Palette) -> Image.Image:
    """Corner-to-corner gradient, computed small and upscaled smooth."""
    gw, gh = 160, 90
    small = Image.new("RGB", (gw, gh))
    px = small.load()
    for y in range(gh):
        for x in range(gw):
            t = (x / (gw - 1)) * 0.62 + (y / (gh - 1)) * 0.38
            px[x, y] = _gradient_color(palette.stops, t)
    return small.resize(size, Image.Resampling.BICUBIC)


def _add_glows(img: Image.Image, palette: Palette, layout_index: int) -> Image.Image:
    w, h = img.size
    glow_layer = Image.new("RGB", img.size, (0, 0, 0))
    draw = ImageDraw.Draw(glow_layer)
    centers = _LAYOUTS[layout_index % len(_LAYOUTS)][:2]
    for (nx, ny), color in zip(centers, palette.glows):
        radius = int(h * 0.42)
        dimmed = tuple(int(c * 0.52) for c in color)
        cx, cy = int(nx * w), int(ny * h)
        draw.ellipse(
            (cx - radius, cy - radius, cx + radius, cy + radius), fill=dimmed
        )
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=h * 0.22))
    return ImageChops.screen(img, glow_layer)


def _add_ring(img: Image.Image, palette: Palette, layout_index: int) -> Image.Image:
    w, h = img.size
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    nx, ny = _LAYOUTS[layout_index % len(_LAYOUTS)][2]
    radius = int(h * 0.34)
    cx, cy = int(nx * w), int(ny * h)
    draw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        outline=(*palette.accent, 58),
        width=max(2, int(h * 0.004)),
    )
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=2))
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def _add_grain(img: Image.Image, seed: int, opacity: float = 0.05) -> Image.Image:
    w, h = img.size
    rng = random.Random(seed)
    noise = Image.frombytes("L", (w, h), rng.randbytes(w * h))
    return Image.blend(img, noise.convert("RGB"), opacity)


def _add_vignette(img: Image.Image, strength: int = 78) -> Image.Image:
    w, h = img.size
    mw, mh = 320, 180
    mask = Image.new("L", (mw, mh))
    px = mask.load()
    for y in range(mh):
        for x in range(mw):
            dx = x / (mw - 1) - 0.5
            dy = y / (mh - 1) - 0.5
            dn = (dx * dx + dy * dy) ** 0.5 / 0.7071
            t = min(max((dn - 0.58) / 0.42, 0.0), 1.0)
            px[x, y] = 255 - int(t * t * strength)
    mask = mask.resize(img.size, Image.Resampling.BICUBIC)
    return ImageChops.multiply(img, mask.convert("RGB"))


def _cover_crop(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    w, h = size
    scale = max(w / image.width, h / image.height)
    resized = image.resize(
        (round(image.width * scale), round(image.height * scale)),
        Image.Resampling.LANCZOS,
    )
    left = (resized.width - w) // 2
    top = (resized.height - h) // 2
    return resized.crop((left, top, left + w, top + h))


def _wrap_by_width(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_px: float
) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and draw.textlength(candidate, font=font) > max_px:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _draw_tracked(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, ...],
    tracking: float,
) -> float:
    """Draw *text* with letter spacing; return the end x position."""
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking
    return x


def _add_typography(
    img: Image.Image, title: str, kicker: str, palette: Palette
) -> Image.Image:
    w, h = img.size
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    title_font = _load_font(_BOLD_FONTS, size=int(h * 0.072))
    kicker_font = _load_font(_REGULAR_FONTS, size=int(h * 0.026))
    brand_font = _load_font(_REGULAR_FONTS, size=int(h * 0.017))

    margin_x = int(w * 0.085)
    lines = _wrap_by_width(draw, title, title_font, max_px=w * 0.62)
    line_height = int(title_font.size * 1.16)
    block_height = int(h * 0.026 * 2.6) + len(lines) * line_height
    top = int(h * 0.52 - block_height / 2)

    _draw_tracked(
        draw,
        (margin_x, top),
        kicker.upper(),
        kicker_font,
        fill=(*palette.accent, 235),
        tracking=kicker_font.size * 0.34,
    )
    rule_y = top + int(kicker_font.size * 1.9)
    draw.rectangle(
        (margin_x, rule_y, margin_x + int(w * 0.055), rule_y + max(2, int(h * 0.0035))),
        fill=(*palette.accent, 200),
    )
    text_y = rule_y + int(kicker_font.size * 1.2)
    for line in lines:
        draw.text((margin_x, text_y), line, font=title_font, fill=(*palette.ink, 255))
        text_y += line_height

    draw.text(
        (margin_x, h - int(h * 0.055)),
        "script2video",
        font=brand_font,
        fill=(*palette.accent, 96),
    )
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def render_card(
    title: str,
    kicker: str,
    palette: Palette,
    size: tuple[int, int],
    *,
    seed: int = 0,
    image: Path | None = None,
) -> Image.Image:
    """Render one scene card of *size* pixels (already supersampled).

    When *image* is given it is cover-cropped and darkened for legibility
    instead of generating a gradient composition; typography, grain and
    vignette are applied either way.
    """
    if image is not None:
        base = _cover_crop(Image.open(image).convert("RGB"), size)
        base = ImageChops.multiply(base, Image.new("RGB", size, (165, 165, 165)))
    else:
        base = _base_gradient(size, palette)
        base = _add_glows(base, palette, layout_index=seed)
        base = _add_ring(base, palette, layout_index=seed)

    base = _add_grain(base, seed=seed)
    base = _add_vignette(base)
    return _add_typography(base, title, kicker, palette)


def write_card(
    path: Path,
    title: str,
    kicker: str,
    palette: Palette,
    output_size: tuple[int, int],
    *,
    seed: int = 0,
    image: Path | None = None,
) -> Path:
    """Render and save a card at ``SUPERSAMPLE`` times *output_size*."""
    card_size = (output_size[0] * SUPERSAMPLE, output_size[1] * SUPERSAMPLE)
    card = render_card(title, kicker, palette, card_size, seed=seed, image=image)
    path.parent.mkdir(parents=True, exist_ok=True)
    card.save(path, format="PNG")
    return path
