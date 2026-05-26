"""
Generate the menu bar template icon for tracker.py.

Output: assets/menubar-template.png (44x44, black on transparent).
macOS auto-inverts template images for dark mode — do NOT use any color.

Run: venv/bin/python assets/build-menubar-icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 44                  # @2x of the 22pt menu bar slot
BAR_COUNT = 3
BAR_WIDTH = 8
BAR_RADIUS = 2
GAP = 4                    # horizontal gap between bars
HEIGHTS = [16, 24, 32]     # ascending usage indicator
PADDING_BOTTOM = 6
INK = (0, 0, 0, 255)       # black; template images ignore color


def main() -> None:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    total_w = BAR_COUNT * BAR_WIDTH + (BAR_COUNT - 1) * GAP
    start_x = (SIZE - total_w) // 2
    baseline = SIZE - PADDING_BOTTOM

    for i, h in enumerate(HEIGHTS):
        x0 = start_x + i * (BAR_WIDTH + GAP)
        x1 = x0 + BAR_WIDTH
        y0 = baseline - h
        y1 = baseline
        draw.rounded_rectangle([x0, y0, x1, y1], radius=BAR_RADIUS, fill=INK)

    out = Path(__file__).resolve().parent / "menubar-template.png"
    img.save(out)
    print(f"Wrote {out} ({SIZE}x{SIZE} template image)")


if __name__ == "__main__":
    main()
