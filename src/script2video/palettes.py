"""Named color palettes for program-generated scene backdrops.

Every visual in script2video is generated from these palettes -- no stock
media is used or shipped. A palette drives the layered gradient, the glow
accents, and the typography colors of a scene card.
"""

from __future__ import annotations

from dataclasses import dataclass


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


@dataclass(frozen=True)
class Palette:
    """Colors for one backdrop style.

    stops:  gradient stops, painted corner-to-corner (dark -> lighter).
    glows:  soft radial glow colors layered over the gradient.
    ink:    title / kicker text color.
    accent: accent rule and secondary typography color.
    """

    name: str
    stops: tuple[tuple[int, int, int], ...]
    glows: tuple[tuple[int, int, int], ...]
    ink: tuple[int, int, int]
    accent: tuple[int, int, int]


PALETTES: dict[str, Palette] = {
    p.name: p
    for p in (
        Palette(
            name="midnight",
            stops=(_rgb("#0A0E22"), _rgb("#16224A"), _rgb("#2A3B74")),
            glows=(_rgb("#5B7CFF"), _rgb("#9B6BFF")),
            ink=_rgb("#F2F5FF"),
            accent=_rgb("#7EA0FF"),
        ),
        Palette(
            name="ember",
            stops=(_rgb("#170C09"), _rgb("#3B1C11"), _rgb("#6E351B")),
            glows=(_rgb("#FF9950"), _rgb("#FF5470")),
            ink=_rgb("#FFF3EA"),
            accent=_rgb("#FFB380"),
        ),
        Palette(
            name="kelp",
            stops=(_rgb("#06140F"), _rgb("#0E2F25"), _rgb("#1C523D")),
            glows=(_rgb("#3FDB9C"), _rgb("#6FE3C9")),
            ink=_rgb("#ECFFF7"),
            accent=_rgb("#6FE3B2"),
        ),
        Palette(
            name="slate",
            stops=(_rgb("#0F1215"), _rgb("#20272E"), _rgb("#37424D")),
            glows=(_rgb("#8FB6DB"), _rgb("#6E8CA8")),
            ink=_rgb("#F2F6FA"),
            accent=_rgb("#9FC2E0"),
        ),
        Palette(
            name="aurora",
            stops=(_rgb("#090D28"), _rgb("#1E2260"), _rgb("#153F4C")),
            glows=(_rgb("#45E0C6"), _rgb("#8A7DFF")),
            ink=_rgb("#F0FDFF"),
            accent=_rgb("#63E8CF"),
        ),
        Palette(
            name="dawn",
            stops=(_rgb("#1E1220"), _rgb("#4C2B39"), _rgb("#8A4E45")),
            glows=(_rgb("#FFB27A"), _rgb("#FF7E9C")),
            ink=_rgb("#FFF6EF"),
            accent=_rgb("#FFC9A3"),
        ),
    )
}

DEFAULT_PALETTE = "midnight"


def palette_names() -> list[str]:
    return sorted(PALETTES)


def get_palette(name: str) -> Palette:
    try:
        return PALETTES[name]
    except KeyError:
        known = ", ".join(palette_names())
        raise KeyError(f"unknown palette {name!r} (known: {known})") from None
