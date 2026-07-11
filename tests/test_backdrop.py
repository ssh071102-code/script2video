"""Backdrop generation: sizes, determinism knobs, and the image path."""

from pathlib import Path

from PIL import Image

from script2video.backdrop import SUPERSAMPLE, render_card, write_card
from script2video.palettes import PALETTES, get_palette, palette_names


def test_every_palette_renders(tmp_path: Path) -> None:
    for name in palette_names():
        card = render_card("Title Text", "scene 01", get_palette(name), (320, 180))
        assert card.size == (320, 180)
        assert card.mode == "RGB"


def test_write_card_is_supersampled(tmp_path: Path) -> None:
    out = write_card(
        tmp_path / "cards" / "scene_00.png",
        title="A Longer Title That Needs Wrapping Onto Lines",
        kicker="scene 01",
        palette=get_palette("midnight"),
        output_size=(640, 360),
        seed=3,
    )
    with Image.open(out) as img:
        assert img.size == (640 * SUPERSAMPLE, 360 * SUPERSAMPLE)
        assert img.format == "PNG"


def test_user_image_backdrop(tmp_path: Path) -> None:
    src = tmp_path / "photo.png"
    Image.new("RGB", (200, 900), (200, 120, 40)).save(src)  # extreme aspect
    card = render_card(
        "Over an Image", "scene 02", get_palette("slate"), (320, 180), image=src
    )
    assert card.size == (320, 180)


def test_palette_registry_is_consistent() -> None:
    assert len(PALETTES) >= 4
    for palette in PALETTES.values():
        assert len(palette.stops) >= 2
        assert len(palette.glows) >= 2
        for channel in (*palette.ink, *palette.accent):
            assert 0 <= channel <= 255
