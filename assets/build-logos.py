"""
Generate all logo variants from the 3-ring Activity Ring design.

Outputs:
  - favicon-*.png (16, 32px)
  - logo-*.png (256, 512px) — for GitHub repo, social preview
  - logo-square-512.png — for app icon, social cards
  - logo-social-preview.png (1200x630) — Twitter, OG meta
  - logo-lockup-horizontal.png — "rings + Claude Usage Tracker" text

Run: venv/bin/python assets/build-logos.py
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

SIZE_FINAL = 512         # Base size for logo variants
SCALE = 4                # Oversample for antialiased edges
SIZE = SIZE_FINAL * SCALE

# Ring geometry (scaled to 512px)
RING_RADII = [120, 84, 48]  # outer, middle, inner (at final 512 scale)
STROKE = 18              # stroke width at final scale
INK = (0, 0, 0, 255)     # Black

def render_rings(size_final: int, scale: int = 4) -> Image.Image:
    """Render the 3-ring Activity Ring design at any size."""
    size = size_final * scale
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    center = size // 2

    # Scale ring radii proportionally
    scale_factor = size_final / SIZE_FINAL

    for radius in RING_RADII:
        r = int(radius * scale_factor * scale)
        bbox = [center - r, center - r, center + r, center + r]
        draw.ellipse(bbox, outline=INK, width=int(STROKE * scale_factor * scale))

    return img.resize((size_final, size_final), Image.LANCZOS)

def main() -> None:
    assets_dir = Path(__file__).resolve().parent

    # 1. Generate icon sizes (16, 32, 64, 128, 256, 512)
    for size in [16, 32, 64, 128, 256, 512]:
        img = render_rings(size)
        out = assets_dir / f"logo-{size}.png"
        img.save(out)
        print(f"✓ {out.name}")

    # 2. Favicon variants
    for size in [16, 32]:
        img = render_rings(size)
        out = assets_dir / f"favicon-{size}.png"
        img.save(out)
        print(f"✓ {out.name}")

    # 3. Social preview (1200x630, horizontal)
    # White background, rings on left, text on right
    social = Image.new("RGB", (1200, 630), (255, 255, 255))

    # Draw rings on left side (250px square, centered vertically)
    rings = render_rings(250)
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

    draw.text((text_x, text_y), "Claude Usage Tracker", fill=(0, 0, 0), font=font_large)
    draw.text((text_x, text_y + 90), "macOS menu bar app • Track your API limits in real-time",
              fill=(100, 100, 100), font=font_small)

    out = assets_dir / "logo-social-preview.png"
    social.save(out)
    print(f"✓ {out.name}")

    # 4. Square logo (512x512, for GitHub, Homebrew, etc.)
    logo_square = render_rings(512)
    out = assets_dir / "logo-square-512.png"
    logo_square.save(out)
    print(f"✓ {out.name}")

    print(f"\n✅ All logos generated in {assets_dir}")
    print("\nRecommended usage:")
    print("  - favicon-16.png, favicon-32.png → <link rel='icon'>")
    print("  - logo-256.png → GitHub repo social card")
    print("  - logo-square-512.png → app icon, Homebrew")
    print("  - logo-social-preview.png → Twitter/OG meta tags")

if __name__ == "__main__":
    main()
