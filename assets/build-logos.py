"""
Generate all logo variants from the 2-ring Activity Ring design
(outer = 5-hour window, inner = weekly window — same as the app icon).

Outputs:
  - favicon-*.png (16, 32px)
  - logo-*.png (256, 512px) — for GitHub repo, social preview
  - logo-square-512.png — for app icon, social cards
  - logo-social-preview.png (1200x630) — Twitter, OG meta; embeds the "Tokease" text lockup

Run: venv/bin/python assets/build-logos.py
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import math

SIZE_FINAL = 512         # Base size for logo variants
SCALE = 4                # Oversample for antialiased edges
SIZE = SIZE_FINAL * SCALE

# Ring geometry (scaled to 512px). Same ratio (1:0.7) as the runtime icon's _RING_RADII.
RING_RADII = [120, 84]   # outer (5h), inner (weekly) — at final 512 scale
STROKE = 18              # stroke width at final scale
INK = (0, 0, 0, 255)     # Black

def render_rings(size_final: int, scale: int = 4, fill_pcts: list = None) -> Image.Image:
    """
    Render the 2-ring Activity Ring design at any size.

    Args:
        size_final: Output size in pixels
        scale: Oversample factor for antialiasing
        fill_pcts: List of 2 percentages (0-100) for outer/inner rings (5h/weekly).
                   If None, renders empty rings. If provided, fills each ring to that %.
    """
    size = size_final * scale
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")
    center = size // 2

    # Scale ring radii proportionally
    scale_factor = size_final / SIZE_FINAL
    stroke_width = int(STROKE * scale_factor * scale)

    for idx, radius in enumerate(RING_RADII):
        r = int(radius * scale_factor * scale)
        bbox = [center - r, center - r, center + r, center + r]

        if fill_pcts is None:
            # Empty rings only
            draw.ellipse(bbox, outline=INK, width=stroke_width)
        else:
            # Only draw filled arc (no background track)
            pct = max(0, min(100, fill_pcts[idx]))
            if pct > 0:
                sweep = (pct / 100.0) * 360.0
                # Draw arc with naturally rounded caps (Pillow's default)
                draw.arc(bbox, start=-90, end=-90 + sweep,
                        fill=INK, width=stroke_width)

    return img.resize((size_final, size_final), Image.LANCZOS)

def main() -> None:
    assets_dir = Path(__file__).resolve().parent

    # Example usage percentages for marketing: 70% (5h session), 80% (weekly)
    DEMO_USAGE = [70, 80]

    print("📍 Generating EMPTY rings (baseline)...")
    # 1. Generate icon sizes with empty rings (16, 32, 64, 128, 256, 512)
    for size in [16, 32, 64, 128, 256, 512]:
        img = render_rings(size)
        out = assets_dir / f"logo-{size}.png"
        img.save(out)
        print(f"  ✓ {out.name}")

    # 2. Favicon variants (empty)
    for size in [16, 32]:
        img = render_rings(size)
        out = assets_dir / f"favicon-{size}.png"
        img.save(out)
        print(f"  ✓ {out.name}")

    print("\n📍 Generating FILLED rings (demo usage: 70% / 80%)...")
    # 3. Demo versions with 70/80 usage (for marketing)
    for size in [128, 256, 512]:
        img = render_rings(size, fill_pcts=DEMO_USAGE)
        out = assets_dir / f"logo-{size}-demo.png"
        img.save(out)
        print(f"  ✓ {out.name}")

    # 4. Social preview (1200x630, horizontal) with demo rings
    print("\n📍 Generating social preview (1200x630)...")
    social = Image.new("RGB", (1200, 630), (255, 255, 255))

    # Draw rings on left side (250px square, centered vertically)
    rings = render_rings(250, fill_pcts=DEMO_USAGE)
    rings_x = 100
    rings_y = (630 - 250) // 2
    social.paste(rings, (rings_x, rings_y), rings)

    # Draw text on right side
    draw = ImageDraw.Draw(social)
    try:
        # Try to use a nice font; fallback to default
        font_large = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 72)
        font_small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 24)
    except:
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    text_x = 450
    text_y = 150

    draw.text((text_x, text_y), "Tokease", fill=(0, 0, 0), font=font_large)
    # Two lines to fit in 1200px without truncation, keeping the wedge.
    draw.text((text_x, text_y + 90), "Your Claude 5h & weekly limits, in the menu bar.",
              fill=(100, 100, 100), font=font_small)
    draw.text((text_x, text_y + 122), "No token read. Conformant by construction.",
              fill=(100, 100, 100), font=font_small)

    out = assets_dir / "logo-social-preview.png"
    social.save(out)
    print(f"  ✓ {out.name}")

    # 5. Square logo (512x512, for GitHub, Homebrew, etc.) - demo version
    print("\n📍 Generating square logo (512x512)...")
    logo_square = render_rings(512, fill_pcts=DEMO_USAGE)
    out = assets_dir / "logo-square-512.png"
    logo_square.save(out)
    print(f"  ✓ {out.name}")

    print(f"\n✅ All logos generated in {assets_dir}")
    print("\n📊 Files created:")
    print("  Empty rings (baseline):")
    print("    - favicon-16.png, favicon-32.png")
    print("    - logo-16/32/64/128/256/512.png")
    print("  Demo usage (70%/80%):")
    print("    - logo-128-demo.png, logo-256-demo.png, logo-512-demo.png")
    print("    - logo-social-preview.png (1200x630)")
    print("    - logo-square-512.png")
    print("\n💡 Use the -demo versions for marketing (shows actual tracking in action)")

if __name__ == "__main__":
    main()
