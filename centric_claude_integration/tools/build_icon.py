"""Render the module icon from the Claude mark the UI already uses.

Not loaded by Odoo. It reads the sunburst path straight out of
static/src/xml/claude_systray.xml and rasterises it, so the icon in the Apps
list is the same mark as the one in the navbar and the workspace header. If the
mark is ever redrawn, run this again rather than editing the PNG:

    python tools/build_icon.py

Colours are the module's own: the tile is --cc-bg from claude_workspace.scss,
the blades are $cc-brand. Both are read from the stylesheet rather than copied
here, so the icon cannot drift away from the product it labels.

Needs Pillow. The path only ever uses M, Q and Z, so it is flattened by hand
rather than pulling in a full SVG rasteriser.
"""

import io
import math
import os
import re
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE = os.path.dirname(HERE)

SIZE = 512
# The house style in this repository: a rounded tile with the glyph centred.
# 17.6% of the edge is the corner radius the other icons use.
RADIUS = round(SIZE * 0.176)
GLYPH_SCALE = 0.60
# Rasterise large and shrink; the blades are thin and would alias badly at 1x.
SUPERSAMPLE = 4
# The mark is authored in a 24x24 viewBox.
VIEWBOX = 24.0
# Segments per quadratic. The blades are small and smooth; 24 is past the point
# where more makes any visible difference after downsampling.
STEPS = 24


def read_text(relative):
    return io.open(os.path.join(MODULE, relative), encoding="utf-8").read()


def brand_colours():
    scss = read_text("static/src/scss/claude_workspace.scss")
    brand = re.search(r"\$cc-brand:\s*(#[0-9a-fA-F]{6})", scss)
    background = re.search(r"--cc-bg:\s*(#[0-9a-fA-F]{6})", scss)
    if not brand or not background:
        raise SystemExit("Could not read $cc-brand / --cc-bg from the stylesheet.")
    return brand.group(1), background.group(1)


def mark_path():
    xml = read_text("static/src/xml/claude_systray.xml")
    found = re.search(r'<path fill="currentColor" d="([^"]+)"', xml)
    if not found:
        raise SystemExit("Could not find the Claude mark path in the systray template.")
    return found.group(1)


def parse_subpaths(data):
    """Flatten an M/Q/Z path into closed polygons.

    Only the three commands the mark actually uses are handled. Anything else
    is a redraw of the mark, and should be met with a clear failure rather than
    a silently wrong icon.
    """
    tokens = re.findall(r"([MQZ])([^MQZ]*)", data)
    subpaths, current, cursor = [], [], (0.0, 0.0)
    for command, raw in tokens:
        numbers = [float(n) for n in re.findall(r"-?\d*\.?\d+", raw)]
        if command == "M":
            if current:
                subpaths.append(current)
            cursor = (numbers[0], numbers[1])
            current = [cursor]
        elif command == "Q":
            for i in range(0, len(numbers), 4):
                cx, cy, x, y = numbers[i : i + 4]
                x0, y0 = cursor
                for step in range(1, STEPS + 1):
                    t = step / STEPS
                    u = 1 - t
                    current.append(
                        (
                            u * u * x0 + 2 * u * t * cx + t * t * x,
                            u * u * y0 + 2 * u * t * cy + t * t * y,
                        )
                    )
                cursor = (x, y)
        elif command == "Z":
            if current:
                subpaths.append(current)
                current = []
    if current:
        subpaths.append(current)
    return subpaths


def main():
    brand, background = brand_colours()
    subpaths = parse_subpaths(mark_path())
    if len(subpaths) != 11:
        print("warning: expected 11 blades, got %d" % len(subpaths), file=sys.stderr)

    big = SIZE * SUPERSAMPLE
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        [0, 0, big - 1, big - 1], radius=RADIUS * SUPERSAMPLE, fill=background
    )

    glyph = big * GLYPH_SCALE
    scale = glyph / VIEWBOX
    offset = (big - glyph) / 2

    def place(x, y):
        return offset + x * scale, offset + y * scale

    for polygon in subpaths:
        draw.polygon([place(x, y) for x, y in polygon], fill=brand)

    # Every blade stops about 1.5 units short of the middle, so the eleven of
    # them leave a hole where the mark is meant to be solid. At navbar size it
    # is sub-pixel and nobody has ever seen it; at 512 it is an obvious dark
    # dot. The disc is measured off the blades rather than guessed, so a
    # redrawn mark still closes cleanly.
    points = [point for polygon in subpaths for point in polygon]
    cx = sum(x for x, _ in points) / len(points)
    cy = sum(y for _, y in points) / len(points)
    inner = max(
        min(math.hypot(x - cx, y - cy) for x, y in polygon) for polygon in subpaths
    ) * 1.06
    left, top = place(cx - inner, cy - inner)
    right, bottom = place(cx + inner, cy + inner)
    draw.ellipse([left, top, right, bottom], fill=brand)

    icon = image.resize((SIZE, SIZE), Image.LANCZOS)
    out_dir = os.path.join(MODULE, "static", "description")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "icon.png")
    icon.save(out, optimize=True)
    print(
        "wrote %s  %dx%d  tile=%s  blades=%s  %d bytes"
        % (out, SIZE, SIZE, background, brand, os.path.getsize(out))
    )


if __name__ == "__main__":
    main()
