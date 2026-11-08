"""Generate every brand asset from one palette.

Run from the repository root:  python docs/brand/build_brand.py

Needs Pillow, fontTools and ImageMagick with SVG support. Text uses the
Poppins files in docs/brand/fonts and is converted to outlines, so the SVG
files do not depend on any installed font.
"""

import subprocess
import tempfile
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
BRAND_DIR = ROOT / "custom_components" / "irrigation" / "brand"
OUT_DIR = ROOT / "docs" / "brand"

SLATE = "#121C2B"
GREEN = "#2C5E43"
BLUE = "#0284C7"
AMBER = "#F59E0B"
WHITE = "#FFFFFF"

# Tints for dark surfaces, where the core green and blue lack contrast.
GREEN_ON_DARK = "#4CAF7D"
BLUE_ON_DARK = "#38BDF8"
SLATE_RAISED = "#1C2940"
SLATE_LINE = "#2B3B55"
MUTED_ON_DARK = "#9FB0C7"
MUTED_ON_LIGHT = "#4A5A70"
SURFACE_LIGHT = "#EEF2F7"
LINE_LIGHT = "#D3DCE7"

FONT_DIR = OUT_DIR / "fonts"
BOLD = TTFont(FONT_DIR / "Poppins-Bold.ttf")
REGULAR = TTFont(FONT_DIR / "Poppins-Regular.ttf")

# Poppins has a narrow space, which crowds short labels such as "Zone 1".
WORD_SPACE = 0.08

WORDMARK = "irrigation-ha"
TAGLINE = "SMART IRRIGATION TECH"

DROP = "M256 20C232 96 88 214 88 322A168 168 0 0 0 424 322C424 214 280 96 256 20Z"


def text_path(text, font, size, x, y, fill, tracking=0.0, anchor="start"):
    """Return an SVG path for text, and its advance width."""
    glyphs = font.getGlyphSet()
    cmap = font.getBestCmap()
    scale = size / font["head"].unitsPerEm
    names = [cmap[ord(c)] for c in text]
    advances = []
    for char, name in zip(text, names):
        advance = glyphs[name].width * scale + tracking
        if char == " ":
            advance += size * WORD_SPACE
        advances.append(advance)
    width = sum(advances) - tracking
    pen_x = x - {"start": 0, "middle": width / 2, "end": width}[anchor]
    parts = []
    for name, advance in zip(names, advances):
        pen = SVGPathPen(glyphs, ntos=lambda v: f"{v:.2f}".rstrip("0").rstrip("."))
        glyphs[name].draw(TransformPen(pen, (scale, 0, 0, -scale, pen_x, y)))
        parts.append(pen.getCommands())
        pen_x += advance
    return f'<path fill="{fill}" d="{"".join(parts)}"/>', width


def text_width(text, font, size, tracking=0.0):
    return text_path(text, font, size, 0, 0, WHITE, tracking)[1]


def leaf(x, y, length, width, angle, vein):
    """A leaf growing from (x, y), rotated clockwise from pointing up."""
    half = width / 2
    return (
        f'<g transform="translate({x} {y}) rotate({angle})">'
        f'<path fill="{WHITE}" d="M0 0C{-half} {-length * 0.25} {-half} {-length * 0.72} 0 {-length}'
        f'C{half} {-length * 0.72} {half} {-length * 0.25} 0 0Z"/>'
        f'<path fill="none" stroke="{vein}" stroke-width="7" stroke-linecap="round" '
        f'd="M0 {-length * 0.14}L0 {-length * 0.74}"/></g>'
    )


def mark(clip_id="drop"):
    """The drop: plant on the left, circuit on the right, on a 512 unit grid."""
    traces = [
        ("M256 428L350 334V318", 350, 300, WHITE),
        ("M256 340L300 296V206", 300, 186, AMBER),
        ("M256 470H306L362 414", 372, 404, WHITE),
    ]
    trace_svg = "".join(
        f'<path fill="none" stroke="{WHITE}" stroke-width="17" stroke-linejoin="round" d="{d}"/>'
        f'<circle cx="{cx}" cy="{cy}" r="22" fill="{fill}"/>'
        for d, cx, cy, fill in traces
    )
    return (
        f'<clipPath id="{clip_id}"><path d="{DROP}"/></clipPath>'
        f'<g clip-path="url(#{clip_id})">'
        f'<rect x="0" y="0" width="256" height="512" fill="{GREEN}"/>'
        f'<rect x="256" y="0" width="256" height="512" fill="{BLUE}"/>'
        f"{trace_svg}"
        f'{leaf(250, 440, 158, 92, -62, GREEN)}'
        f'{leaf(250, 340, 134, 80, -48, GREEN)}'
        f'{leaf(252, 244, 98, 60, -30, GREEN)}'
        f'<path fill="{WHITE}" d="M243 500L250 112Q256 96 262 112L269 500Z"/>'
        f"</g>"
    )


def svg(width, height, body):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">{body}</svg>\n'
    )


def icon_svg():
    return svg(
        512,
        512,
        f'<defs><radialGradient id="glow" cx="50%" cy="54%" r="52%">'
        f'<stop offset="0%" stop-color="{BLUE}" stop-opacity="0.5"/>'
        f'<stop offset="100%" stop-color="{BLUE}" stop-opacity="0"/></radialGradient></defs>'
        f'<rect x="4" y="4" width="504" height="504" rx="112" fill="{SLATE}" '
        f'stroke="{SLATE_LINE}" stroke-width="8"/>'
        f'<rect x="8" y="8" width="496" height="496" rx="108" fill="url(#glow)"/>'
        f'<g transform="translate(25.6 25.6) scale(0.9)">{mark()}</g>',
    )


def mark_svg():
    return svg(512, 512, mark())


def logo_svg(word_fill, tag_fill):
    """A horizontal lockup, trimmed to the art at a height of 256."""
    height = 256
    drop_scale = height / 480
    drop_width = 336 * drop_scale
    gap = 26
    size = 102
    tag_size = 30
    word_width = text_width(WORDMARK, BOLD, size)
    natural = text_width(TAGLINE, REGULAR, tag_size)
    tracking = (word_width - natural) / (len(TAGLINE) - 1)
    text_x = drop_width + gap
    word, _ = text_path(WORDMARK, BOLD, size, text_x, 138, word_fill)
    tag, _ = text_path(TAGLINE, REGULAR, tag_size, text_x, 203, tag_fill, tracking)
    width = round(text_x + word_width + 4)
    art = f'<g transform="scale({drop_scale}) translate(-88 -18)">{mark()}</g>'
    return svg(width, height, art + word + tag)


def zone_card(x, y, width, height, name, state, detail, colour, progress):
    name_svg, _ = text_path(name, BOLD, 24, x + 26, y + 46, WHITE)
    state_svg, _ = text_path(state, BOLD, 19, x + 26, y + 86, colour)
    detail_svg, _ = text_path(detail, REGULAR, 19, x + width - 26, y + 86, MUTED_ON_DARK, anchor="end")
    track_y = y + height - 34
    track_width = width - 52
    return (
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="18" fill="{SLATE_RAISED}" '
        f'stroke="{SLATE_LINE}" stroke-width="2"/>'
        f'<circle cx="{x + width - 36}" cy="{y + 38}" r="9" fill="{colour}"/>'
        f"{name_svg}{state_svg}{detail_svg}"
        f'<rect x="{x + 26}" y="{track_y}" width="{track_width}" height="10" rx="5" fill="{SLATE_LINE}"/>'
        f'<rect x="{x + 26}" y="{track_y}" width="{track_width * progress:.0f}" height="10" rx="5" '
        f'fill="{colour}"/>'
    )


def banner_svg():
    width, height = 1280, 640
    grid = "".join(
        f'<path stroke="{SLATE_LINE}" stroke-opacity="0.45" stroke-width="1" d="M{x} 0V{height}"/>'
        for x in range(64, width, 64)
    ) + "".join(
        f'<path stroke="{SLATE_LINE}" stroke-opacity="0.45" stroke-width="1" d="M0 {y}H{width}"/>'
        for y in range(64, height, 64)
    )
    drop_scale = 300 / 480
    art = f'<g transform="translate(70 64) scale({drop_scale}) translate(-88 -18)">{mark()}</g>'

    text_x = 322
    word, word_width = text_path(WORDMARK, BOLD, 104, text_x, 196, WHITE)
    natural = text_width(TAGLINE, REGULAR, 31)
    tracking = (word_width - natural) / (len(TAGLINE) - 1)
    tag, _ = text_path(TAGLINE, REGULAR, 31, text_x, 262, MUTED_ON_DARK, tracking)
    strap, _ = text_path("Local zone control for Home Assistant", REGULAR, 24, text_x, 322, WHITE)
    badge_width = text_width("HACS compatible", BOLD, 19)
    pill_width = badge_width + 40
    pill_x = text_x + word_width - pill_width
    badge, _ = text_path("HACS compatible", BOLD, 19, pill_x + 20, 320, WHITE)
    pill = f'<rect x="{pill_x:.1f}" y="294" width="{pill_width:.1f}" height="38" rx="19" fill="{BLUE}"/>'

    cards = [
        ("Zone 1", "Done", "5:00", GREEN_ON_DARK, 1.0),
        ("Zone 2", "Running", "4:12 left", BLUE_ON_DARK, 0.58),
        ("Zone 3", "Up next", "5:00", AMBER, 0.0),
        ("Zone 4", "Idle", "10:00", MUTED_ON_DARK, 0.0),
    ]
    card_width, card_gap, card_y, card_height = 278, 20, 404, 160
    card_svg = "".join(
        zone_card(70 + i * (card_width + card_gap), card_y, card_width, card_height, *card)
        for i, card in enumerate(cards)
    )
    body = (
        f'<defs><radialGradient id="glow" cx="16%" cy="34%" r="58%">'
        f'<stop offset="0%" stop-color="{BLUE}" stop-opacity="0.34"/>'
        f'<stop offset="100%" stop-color="{BLUE}" stop-opacity="0"/></radialGradient></defs>'
        f'<rect width="{width}" height="{height}" fill="{SLATE}"/>{grid}'
        f'<rect width="{width}" height="{height}" fill="url(#glow)"/>'
        f"{art}{word}{tag}{strap}{pill}{badge}{card_svg}"
    )
    return svg(width, height, body)


def render(svg_text, out_path, width, height):
    """Rasterise at 4x, downsample, then rewrite the PNG with no metadata."""
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "art.svg"
        raster = Path(tmp) / "art.png"
        source.write_text(svg_text, encoding="utf-8")
        subprocess.run(
            ["magick", "-background", "none", "-density", "384", str(source),
             "-filter", "Lanczos", "-resize", f"{width}x{height}!", f"PNG32:{raster}"],
            check=True,
        )
        with Image.open(raster) as image:
            clean = Image.new("RGBA", image.size)
            clean.paste(image.convert("RGBA"))
    if clean.getextrema()[3][0] == 255:
        clean = clean.convert("RGB")
    clean.save(out_path, optimize=True)


def logo_size(svg_text, height):
    natural = int(svg_text.split('width="')[1].split('"')[0])
    return round(natural * height / 256), height


def theme_yaml():
    """A Home Assistant theme: native CSS variables, no custom cards needed."""
    shared = {
        "irrigation-slate": SLATE,
        "irrigation-green": GREEN,
        "irrigation-blue": BLUE,
        "irrigation-amber": AMBER,
        "irrigation-warning-color": "var(--irrigation-amber)",
    }
    light = {
        "primary-color": BLUE,
        "accent-color": BLUE,
        "primary-background-color": SURFACE_LIGHT,
        "secondary-background-color": SURFACE_LIGHT,
        "card-background-color": WHITE,
        "ha-card-background": WHITE,
        "ha-card-border-color": LINE_LIGHT,
        "app-header-background-color": SLATE,
        "app-header-text-color": WHITE,
        "primary-text-color": SLATE,
        "secondary-text-color": MUTED_ON_LIGHT,
        "divider-color": LINE_LIGHT,
        "state-icon-color": BLUE,
        "state-active-color": BLUE,
        "state-switch-active-color": BLUE,
        "success-color": GREEN,
        "warning-color": AMBER,
        "irrigation-valve-active-color": BLUE,
        "irrigation-moisture-color": GREEN,
    }
    dark = {
        "primary-color": BLUE_ON_DARK,
        "accent-color": BLUE_ON_DARK,
        "primary-background-color": SLATE,
        "secondary-background-color": SLATE_RAISED,
        "card-background-color": SLATE_RAISED,
        "ha-card-background": SLATE_RAISED,
        "ha-card-border-color": SLATE_LINE,
        "app-header-background-color": SLATE,
        "app-header-text-color": WHITE,
        "primary-text-color": WHITE,
        "secondary-text-color": MUTED_ON_DARK,
        "divider-color": SLATE_LINE,
        "state-icon-color": BLUE_ON_DARK,
        "state-active-color": BLUE_ON_DARK,
        "state-switch-active-color": BLUE_ON_DARK,
        "success-color": GREEN_ON_DARK,
        "warning-color": AMBER,
        "irrigation-valve-active-color": BLUE_ON_DARK,
        "irrigation-moisture-color": GREEN_ON_DARK,
    }
    lines = ["# Generated by build_brand.py. Edit the palette there, not here.", "Irrigation:"]
    lines += [f'  {key}: "{value}"' for key, value in shared.items()]
    lines.append("  modes:")
    for mode, values in (("light", light), ("dark", dark)):
        lines.append(f"    {mode}:")
        lines += [f'      {key}: "{value}"' for key, value in values.items()]
    return "\n".join(lines) + "\n"


def palette_css():
    """The same variables for card-mod or a custom card's stylesheet."""
    return f"""/* Generated by build_brand.py. Edit the palette there, not here. */
:host, :root {{
  --irrigation-slate: {SLATE};
  --irrigation-green: {GREEN};
  --irrigation-blue: {BLUE};
  --irrigation-amber: {AMBER};
  --irrigation-green-on-dark: {GREEN_ON_DARK};
  --irrigation-blue-on-dark: {BLUE_ON_DARK};
  --irrigation-valve-active-color: var(--irrigation-blue);
  --irrigation-moisture-color: var(--irrigation-green);
  --irrigation-warning-color: var(--irrigation-amber);
}}
"""


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    icon = icon_svg()
    light_logo = logo_svg(SLATE, MUTED_ON_LIGHT)
    dark_logo = logo_svg(WHITE, MUTED_ON_DARK)
    banner = banner_svg()

    for name, text in (
        ("mark.svg", mark_svg()),
        ("icon.svg", icon),
        ("logo.svg", light_logo),
        ("dark_logo.svg", dark_logo),
        ("banner.svg", banner),
    ):
        (OUT_DIR / name).write_text(text, encoding="utf-8")
    (ROOT / "custom_components" / "irrigation" / "frontend" / "mark.svg").write_text(
        mark_svg(), encoding="utf-8"
    )

    render(icon, BRAND_DIR / "icon.png", 256, 256)
    render(icon, BRAND_DIR / "icon@2x.png", 512, 512)
    for prefix, text in (("logo", light_logo), ("dark_logo", dark_logo)):
        render(text, BRAND_DIR / f"{prefix}.png", *logo_size(text, 128))
        render(text, BRAND_DIR / f"{prefix}@2x.png", *logo_size(text, 256))
    render(banner, ROOT / "docs" / "banner.png", 1280, 640)

    (OUT_DIR / "irrigation-theme.yaml").write_text(theme_yaml(), encoding="utf-8")
    (OUT_DIR / "irrigation-colors.css").write_text(palette_css(), encoding="utf-8")


if __name__ == "__main__":
    main()
