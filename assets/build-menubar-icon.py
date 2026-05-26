"""
Generate the menu bar template icon for tracker.py.

Output: assets/menubar-template.png (44x44, black on transparent).
macOS auto-inverts template images for dark mode — do NOT use any color.

Design: three concentric rings (Activity-Ring metaphor) representing the
three layers of usage data the app surfaces — 5-hour session, weekly
window, per-model split.

Run: venv/bin/python assets/build-menubar-icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

SIZE_FINAL = 44              # @2x of the 22pt menu bar slot
SCALE = 4                    # oversample for antialiased ring edges
SIZE = SIZE_FINAL * SCALE    # 176 internal canvas

# Ring radii at FINAL scale (44x44). Stroke renders INWARD from the bbox edge,
# so a bbox radius of 20 with stroke 3 produces a ring spanning r=17 to r=20.
RING_RADII = [20, 14, 8]     # outer, middle, inner
STROKE = 3                   # stroke width at final scale (rendered as 12 at SCALE)
INK = (0, 0, 0, 255)         # template images ignore color; macOS tints in render


def main() -> None:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    center = SIZE // 2

    for radius in RING_RADII:
        r = radius * SCALE
        bbox = [center - r, center - r, center + r, center + r]
        draw.ellipse(bbox, outline=INK, width=STROKE * SCALE)

    img = img.resize((SIZE_FINAL, SIZE_FINAL), Image.LANCZOS)
    out = Path(__file__).resolve().parent / "menubar-template.png"
    img.save(out)
    print(f"Wrote {out} ({SIZE_FINAL}x{SIZE_FINAL} template image, 3 concentric rings)")


if __name__ == "__main__":
    main()
