"""
Generate all logo variants from the 2-ring Activity Ring design, in the
landing's colors: outer ring purple (5-hour), inner ring cyan (weekly).

Outputs:
  - favicon-*.png (16, 32px) — full-circle colored rings (reads well tiny)
  - logo-*.png (256, 512px) — full-circle colored rings, for GitHub repo
  - logo-*-demo.png — partial arcs at the landing's 77% / 35% over faint tracks
  - logo-square-512.png — demo version, for app icon and social cards
  - logo-social-preview.png (1200x630) — Twitter/OG meta, "Tokease" lockup

The menu bar runtime icon stays monochrome template (macOS convention, it must
invert with the theme) — this file only governs brand/marketing assets.

Run: venv/bin/python assets/build-logos.py
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

SIZE_FINAL = 512         # Base size for logo variants
SCALE = 4                # Oversample for antialiased edges

# Ring geometry (scaled to 512px). Same ratio (1:0.7) as the runtime icon's _RING_RADII.
RING_RADII = [120, 84]   # outer (5h), inner (weekly) — at final 512 scale
STROKE = 18              # stroke width at final scale

# Landing palette (docs/index.html hero rings)
RING_COLORS = [
    (168, 85, 247, 255),   # outer, purple #a855f7 (5-hour)
    (34, 211, 238, 255),   # inner, cyan  #22d3ee (weekly)
]
TRACK = (127, 127, 127, 60)  # faint neutral track behind partial arcs

# Demo fills mirror the landing hero exactly (aria-label: 77% / 35%)
DEMO_USAGE = [77, 35]


def render_rings(size_final: int, scale: int = 4, fill_pcts: list = None) -> Image.Image:
    """
    Render the 2-ring design at any size, in brand colors.

    fill_pcts None → full-circle rings (the brand mark).
    fill_pcts [a, b] → faint tracks + colored arcs filled to a% / b%.
    """
    size = size_final * scale
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")
    center = size // 2

    scale_factor = size_final / SIZE_FINAL
    stroke_width = max(1, int(STROKE * scale_factor * scale))

    for idx, radius in enumerate(RING_RADII):
        r = int(radius * scale_factor * scale)
        bbox = [center - r, center - r, center + r, center + r]

        if fill_pcts is None:
            draw.ellipse(bbox, outline=RING_COLORS[idx], width=stroke_width)
        else:
            draw.ellipse(bbox, outline=TRACK, width=stroke_width)
            pct = max(0, min(100, fill_pcts[idx]))
            if pct > 0:
                sweep = (pct / 100.0) * 360.0
                draw.arc(bbox, start=-90, end=-90 + sweep,
                         fill=RING_COLORS[idx], width=stroke_width)

    return img.resize((size_final, size_final), Image.LANCZOS)


def main() -> None:
    assets_dir = Path(__file__).resolve().parent

    print("📍 Generating brand mark (full colored rings)...")
    for size in [16, 32, 64, 128, 256, 512]:
        img = render_rings(size)
        out = assets_dir / f"logo-{size}.png"
        img.save(out)
        print(f"  ✓ {out.name}")

    for size in [16, 32]:
        img = render_rings(size)
        out = assets_dir / f"favicon-{size}.png"
        img.save(out)
        print(f"  ✓ {out.name}")

    print(f"\n📍 Generating FILLED rings (demo usage: {DEMO_USAGE[0]}% / {DEMO_USAGE[1]}%)...")
    for size in [128, 256, 512]:
        img = render_rings(size, fill_pcts=DEMO_USAGE)
        out = assets_dir / f"logo-{size}-demo.png"
        img.save(out)
        print(f"  ✓ {out.name}")

    print("\n📍 Generating social preview (1200x630)...")
    # Dark background matching the landing (--bg: #09090b)
    social = Image.new("RGB", (1200, 630), (9, 9, 11))

    rings = render_rings(250, fill_pcts=DEMO_USAGE)
    rings_x = 100
    rings_y = (630 - 250) // 2
    social.paste(rings, (rings_x, rings_y), rings)

    draw = ImageDraw.Draw(social)
    try:
        font_large = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 72)
        font_small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 24)
    except OSError:
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    text_x = 450
    text_y = 220

    draw.text((text_x, text_y), "Tokease", fill=(250, 250, 250), font=font_large)
    # Two lines to fit in 1200px without truncation, keeping the wedge.
    draw.text((text_x, text_y + 90), "Your Claude 5h & weekly limits, in the menu bar.",
              fill=(161, 161, 170), font=font_small)
    draw.text((text_x, text_y + 122), "No token read. Token-free by construction.",
              fill=(161, 161, 170), font=font_small)

    out = assets_dir / "logo-social-preview.png"
    social.save(out)
    print(f"  ✓ {out.name}")

    print("\n📍 Generating square logo (512x512)...")
    logo_square = render_rings(512, fill_pcts=DEMO_USAGE)
    out = assets_dir / "logo-square-512.png"
    logo_square.save(out)
    print(f"  ✓ {out.name}")

    print(f"\n✅ All logos generated in {assets_dir}")
    print("💡 Use the -demo versions for marketing (shows actual tracking in action)")


if __name__ == "__main__":
    main()
