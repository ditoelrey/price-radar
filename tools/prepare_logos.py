#!/usr/bin/env python3
"""Prepare merchant logos for the offer table.

Source logos arrive at wildly different aspect ratios -- Sport Vision is a
wide wordmark sitting in a 400x400 square, Megasport a 300x200 canvas holding
a 236x33 strip. Dropped straight into a fixed box with ``object-contain``,
each one is letterboxed by its *canvas* rather than its content, so the column
looks ragged for reasons that have nothing to do with the logos themselves.

So each file is trimmed to its actual content before it ships:

    merchant        canvas      content     ratio
    sportvision     400x400     307x70      1.00 -> 4.39
    megasport       300x200     236x33      1.50 -> 7.15
    sportreality    325x90      319x58      3.61 -> 5.50
    sportm          866x288     564x113     3.01 -> 4.99
    buzz            300x144     219x63      2.08 -> 3.48
    sizeer          375x126     323x91      2.98 -> 3.55

Afterwards every ratio exceeds the display box's, so all six render at the
same width and centre vertically -- a tidy column, which is what uniform
actually means here. Logos of different proportions cannot share both a width
and a height, and pretending otherwise just moves the distortion into the
image.

Output is checked in, so this only needs re-running when a logo changes.
Requires Pillow, which is not a project dependency for that reason:

    pip install pillow
    python tools/prepare_logos.py <source-dir>
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    sys.exit("needs Pillow:  pip install pillow")

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "web" / "public" / "logos"

#: Source filename stem -> merchant slug, matching `merchant.slug`.
SOURCES = {
    "6": "sportvision",
    "7": "sportreality",
    "8": "sizeer",
    "9": "sportm",
    "10": "buzz",
    "11": "megasport",
}

#: A pixel counts as background if it is transparent or near-white.
ALPHA_FLOOR = 12
WHITE_FLOOR = 244
#: Breathing room kept around the content, in pixels of the source image.
MARGIN_RATIO = 0.02


def content_box(image: Image.Image) -> tuple[int, int, int, int] | None:
    pixels = image.load()
    width, height = image.size
    min_x, min_y, max_x, max_y = width, height, -1, -1
    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]
            if a > ALPHA_FLOOR and not (r > WHITE_FLOOR and g > WHITE_FLOOR
                                        and b > WHITE_FLOOR):
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
    if max_x < 0:
        return None
    return min_x, min_y, max_x + 1, max_y + 1


def has_opaque_background(image: Image.Image) -> bool:
    """Whether the corners are opaque, i.e. the logo is matted onto white.

    Those are the ones that need `mix-blend-multiply` in the UI; a logo with a
    transparent background already sits on the row cleanly and blending it
    would only risk damaging it.
    """
    pixels = image.load()
    width, height = image.size
    corners = [(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)]
    return all(pixels[x, y][3] > 200 for x, y in corners)


def main() -> int:
    source_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if not source_dir or not source_dir.is_dir():
        return int(bool(sys.exit("usage: prepare_logos.py <source-dir>")))

    OUT.mkdir(parents=True, exist_ok=True)
    print(f"  {'merchant':<14}{'source':<12}{'trimmed':<12}{'ratio':<8}background")
    for stem, slug in SOURCES.items():
        source = source_dir / f"{stem}.png"
        if not source.exists():
            print(f"  {slug:<14}MISSING {source}")
            continue

        image = Image.open(source).convert("RGBA")
        opaque = has_opaque_background(image)
        box = content_box(image)
        if box is None:
            print(f"  {slug:<14}empty image, skipped")
            continue

        margin = int(max(image.size) * MARGIN_RATIO)
        left = max(0, box[0] - margin)
        top = max(0, box[1] - margin)
        right = min(image.width, box[2] + margin)
        bottom = min(image.height, box[3] + margin)
        trimmed = image.crop((left, top, right, bottom))

        target = OUT / f"{slug}.png"
        trimmed.save(target, "PNG", optimize=True)
        w, h = trimmed.size
        print(f"  {slug:<14}{f'{image.width}x{image.height}':<12}"
              f"{f'{w}x{h}':<12}{w / h:<8.2f}"
              f"{'opaque (needs blend)' if opaque else 'transparent'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
