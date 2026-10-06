"""Card primitives following the LenBot panel design: neutral surfaces, brand pink as accent only.

All sizes are logical pixels; images render at 2x. Every piece of text goes through the font chain,
so a symbol the main font lacks is drawn with the next font instead of a missing-glyph box.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from io import BytesIO
import math
from pathlib import Path
from typing import Sequence
import unicodedata

from PIL import Image, ImageDraw, ImageFont, ImageOps
import regex

# Panel palette (src/len_bot/web/frontend/src/styles/theme.js).
BRAND = "#e799b0"
BRAND_SOFT = "#fbeff3"
PRIMARY = "#b4476a"
INK = "#1d1b20"
MUTED = "#6b6870"
LINE = "#e9e9ec"
PAGE = "#f7f7f8"
SURFACE = "#ffffff"
TRACK = "#ededf0"
HOVER = "#f2f2f4"
SUCCESS, SUCCESS_BG = "#22875a", "#e6f4ec"
ERROR, ERROR_BG = "#c4323f", "#fce9ea"
TINTS = [("#f8e6ec", "#a8405f"), ("#eee8f6", "#6c4f96"), ("#f8ece0", "#93552a"),
         ("#e4f1ec", "#2a7457"), ("#e6edf6", "#3d6596"), ("#f5efdc", "#7d6418")]

S = 2
WIDTH = 540
MARGIN = 14
PAD = 22
RADIUS = 12
MAX_PNG_BYTES = 3_000_000


def px(value: float) -> int:
    return round(value * S)


# ---------- fonts ----------

_NOTDEF_PROBE = "\U000F0000"   # Supplementary private use; no CJK font maps it.


@lru_cache(maxsize=None)
def _signature(font: ImageFont.FreeTypeFont, text: str) -> tuple:
    mask = font.getmask(text)
    return mask.size, bytes(mask)


@lru_cache(maxsize=65536)
def has_glyph(font: ImageFont.FreeTypeFont, char: str) -> bool:
    if char.isspace():
        return True
    return _signature(font, char) != _signature(font, _NOTDEF_PROBE)


@dataclass(frozen=True)
class Fonts:
    regular: Path
    bold: Path
    regular_index: int = 0
    bold_index: int = 0
    fallbacks: tuple[Path, ...] = ()
    # A single-weight family draws bold as a thin same-color stroke.
    fake_bold: bool = False

    @lru_cache(maxsize=64)
    def get(self, size: float, bold: bool = False) -> ImageFont.FreeTypeFont:
        path, index = (self.bold, self.bold_index) if bold and not self.fake_bold else (self.regular, self.regular_index)
        return ImageFont.truetype(str(path), px(size), index=index)

    @lru_cache(maxsize=64)
    def chain(self, size: float, bold: bool = False) -> tuple[ImageFont.FreeTypeFont, ...]:
        return (self.get(size, bold), *(ImageFont.truetype(str(path), px(size)) for path in self.fallbacks))

    def pick(self, cluster: str, size: float, bold: bool = False) -> ImageFont.FreeTypeFont:
        chain = self.chain(size, bold)
        base = next((c for c in cluster if not unicodedata.combining(c) and c not in "︎️‍"), cluster[:1])
        return next((font for font in chain if has_glyph(font, base)), chain[0])


def clusters(text: str) -> list[str]:
    return regex.findall(r"\X", text)


@dataclass(frozen=True)
class Style:
    size: float
    bold: bool = False
    color: str = INK


def stroke(fonts: Fonts, style: Style) -> int:
    return max(1, round(style.size * S * 0.035)) if style.bold and fonts.fake_bold else 0


def segments(fonts: Fonts, text: str, style: Style) -> list[tuple[str, ImageFont.FreeTypeFont]]:
    out: list[tuple[str, ImageFont.FreeTypeFont]] = []
    for cluster in clusters(text):
        font = fonts.pick(cluster, style.size, style.bold)
        if out and out[-1][1] is font:
            out[-1] = (out[-1][0] + cluster, font)
        else:
            out.append((cluster, font))
    return out


def measure(fonts: Fonts, text: str, style: Style) -> int:
    return round(sum(font.getlength(part) for part, font in segments(fonts, text, style)))


def draw_text(canvas: Image.Image, fonts: Fonts, x: float, y: float, text: str, style: Style,
              anchor: str = "lt", color: str | None = None) -> int:
    """Draw one line; anchor is horizontal l/m/r plus vertical t/m. Returns the right edge."""
    primary = fonts.get(style.size, style.bold)
    ascent, descent = primary.getmetrics()
    width = measure(fonts, text, style)
    left = x - width if anchor[0] == "r" else x - width / 2 if anchor[0] == "m" else x
    baseline = y + ascent if anchor[1] == "t" else y + (ascent - descent) / 2
    draw = ImageDraw.Draw(canvas)
    cursor = left
    for part, font in segments(fonts, text, style):
        draw.text((cursor, baseline), part, font=font, fill=color or style.color, anchor="ls",
                  stroke_width=stroke(fonts, style), stroke_fill=color or style.color)
        cursor += font.getlength(part)
    return round(left + width)


def wrap(fonts: Fonts, text: str, style: Style, width: int, max_lines: int | None = None) -> list[str]:
    lines = ["".join(unit[1] for unit in line) for line in layout(fonts, [Run(text)], style, width)]
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and measure(fonts, last + "…", style) > width:
            last = last[:-1]
        lines[-1] = last + "…"
    return lines


# ---------- rich text with inline images (Bilibili emoji) ----------

@dataclass
class Run:
    text: str = ""
    image: Image.Image | None = None


def emoji_size(style: Style) -> int:
    return px(style.size * 1.35)


def layout(fonts: Fonts, runs: Sequence[Run], style: Style, width: int) -> list[list[tuple]]:
    """Lines of ('text', cluster, advance, font) and ('image', image, advance, None); CJK may break anywhere."""
    lines: list[list[tuple]] = [[]]
    used = 0
    icon = emoji_size(style)
    for run in runs:
        if run.image is not None:
            units = [("image", run.image, icon + px(2), None)]
        else:
            units = []
            for cluster in clusters(run.text):
                if cluster in ("\n", "\r\n"):
                    units.append(("break", None, 0, None))
                else:
                    font = fonts.pick(cluster, style.size, style.bold)
                    units.append(("text", cluster, font.getlength(cluster), font))
        for unit in units:
            if unit[0] == "break":
                lines.append([])
                used = 0
                continue
            if used + unit[2] > width and lines[-1]:
                lines.append([])
                used = 0
                if unit[0] == "text" and unit[1].isspace():
                    continue
            lines[-1].append(unit)
            used += unit[2]
    while len(lines) > 1 and not lines[-1]:
        lines.pop()
    return lines


def line_height(style: Style, ratio: float = 1.7) -> int:
    return px(style.size * ratio)


def draw_lines(canvas: Image.Image, fonts: Fonts, lines, x: int, y: int, style: Style, ratio: float = 1.7,
               color: str | None = None, strike: bool = False) -> int:
    height = line_height(style, ratio)
    ascent, descent = fonts.get(style.size, style.bold).getmetrics()
    icon = emoji_size(style)
    draw = ImageDraw.Draw(canvas)
    fill = color or style.color
    for line in lines:
        baseline = y + (height + ascent - descent) // 2
        cursor = x
        index = 0
        while index < len(line):
            kind, value, advance, font = line[index]
            if kind == "image":
                picture = value.convert("RGBA").resize((icon, icon), Image.Resampling.LANCZOS)
                canvas.alpha_composite(picture, (round(cursor + px(1)), y + (height - icon) // 2))
                cursor += advance
                index += 1
                continue
            text, start = "", cursor
            while index < len(line) and line[index][0] == "text" and line[index][3] is font:
                text += line[index][1]
                cursor += line[index][2]
                index += 1
            draw.text((start, baseline), text, font=font, fill=fill, anchor="ls",
                      stroke_width=stroke(fonts, style), stroke_fill=fill)
        if strike:
            mid = y + height // 2
            draw.line((x, mid, cursor, mid), fill=fill, width=px(1))
        y += height
    return y


# ---------- images ----------

def rounded(image: Image.Image, radius: float) -> Image.Image:
    scale = 3
    mask = Image.new("L", (image.width * scale, image.height * scale), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, mask.width - 1, mask.height - 1), radius=px(radius) * scale, fill=255)
    out = Image.new("RGBA", image.size, (0, 0, 0, 0))
    out.paste(image.convert("RGBA"), (0, 0), mask.resize(image.size, Image.Resampling.LANCZOS))
    return out


def cover(image: Image.Image, width: int, height: int) -> Image.Image:
    return ImageOps.fit(ImageOps.exif_transpose(image).convert("RGB"), (width, height), Image.Resampling.LANCZOS)


def circle(image: Image.Image, size: int) -> Image.Image:
    image = cover(image, size, size)
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(image, (0, 0), mask.resize((size, size), Image.Resampling.LANCZOS))
    ring = ImageDraw.Draw(out)
    ring.ellipse((0, 0, size - 1, size - 1), outline=LINE, width=max(1, px(0.5)))
    return out


def draw_mark(canvas: Image.Image, x: int, y: int, size: int, color: str = BRAND) -> None:
    """The LenBot signal mark (lenbot-mark.svg): a dot, an inner arc to the upper right, an outer arc to the lower left."""
    scale = 6
    layer = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    unit = size * scale / 96
    stroke = max(1, round(7 * unit))
    centre = 48 * unit
    # SVG arcs: radius 20 from the top (-110°) clockwise to the right (0°); radius 34 from 70° clockwise to the left (180°).
    for radius, start, end in ((20, -110, 0), (34, 70, 180)):
        r = radius * unit
        outer = r + stroke / 2   # Pillow strokes inward from the box; the SVG radius is the stroke centre.
        d.arc((centre - outer, centre - outer, centre + outer, centre + outer), start, end, fill=color, width=stroke)
        for angle in (start, end):
            cx = centre + r * math.cos(math.radians(angle))
            cy = centre + r * math.sin(math.radians(angle))
            d.ellipse((cx - stroke / 2, cy - stroke / 2, cx + stroke / 2, cy + stroke / 2), fill=color)
    d.ellipse((centre - 8 * unit, centre - 8 * unit, centre + 8 * unit, centre + 8 * unit), fill=color)
    canvas.alpha_composite(layer.resize((size, size), Image.Resampling.LANCZOS), (x, y))


# ---------- small pieces ----------

CHIP = Style(11.5, bold=True)


def chip_width(fonts: Fonts, text: str, style: Style = CHIP, pad_x: float = 7, dot: bool = False) -> int:
    return measure(fonts, text, style) + px(pad_x) * 2 + (px(10) if dot else 0)


def draw_chip(canvas: Image.Image, fonts: Fonts, x: int, y: int, text: str, fg: str, bg: str, *,
              style: Style = CHIP, pad_x: float = 7, height: float = 20, dot: str | None = None) -> int:
    w = chip_width(fonts, text, style, pad_x, bool(dot))
    h = px(height)
    ImageDraw.Draw(canvas).rounded_rectangle((x, y, x + w, y + h), radius=px(6), fill=bg)
    tx = x + px(pad_x)
    if dot:
        r = px(3)
        ImageDraw.Draw(canvas).ellipse((tx, y + h // 2 - r, tx + 2 * r, y + h // 2 + r), fill=dot)
        tx += px(10)
    draw_text(canvas, fonts, tx, y + h / 2, text, style, anchor="lm", color=fg)
    return x + w


def compact(number: int | None) -> str:
    if number is None:
        return "--"
    if number >= 10000:
        return f"{number / 10000:.1f}".rstrip("0").rstrip(".") + "万"
    return str(number)


# ---------- card stack ----------

@dataclass
class Card:
    """Measure-then-draw vertical stack inside one white card on the page background."""
    fonts: Fonts
    blocks: list = field(default_factory=list)

    @property
    def inner(self) -> int:
        return px(WIDTH - 2 * MARGIN - 2 * PAD)

    def add(self, height: int, paint, gap: float = 14) -> None:
        self.blocks.append((height, paint, px(gap)))

    def render(self) -> bytes:
        total = sum(h for h, _, _ in self.blocks) + sum(g for _, _, g in self.blocks[1:])
        height = total + px(2 * MARGIN + 2 * PAD)
        canvas = Image.new("RGBA", (px(WIDTH), height), PAGE)
        ImageDraw.Draw(canvas).rounded_rectangle(
            (px(MARGIN), px(MARGIN), px(WIDTH - MARGIN) - 1, height - px(MARGIN) - 1),
            radius=px(RADIUS), fill=SURFACE, outline=LINE, width=max(1, px(0.5)))
        x, y = px(MARGIN + PAD), px(MARGIN + PAD)
        for index, (h, paint, gap) in enumerate(self.blocks):
            if index:
                y += gap
            paint(canvas, x, y, self.inner)
            y += h
        out = Image.new("RGB", canvas.size, PAGE)
        out.paste(canvas, (0, 0), canvas)
        buffer = BytesIO()
        out.save(buffer, format="PNG", optimize=True)
        if buffer.tell() > MAX_PNG_BYTES:
            # Photo-heavy cards stay sharp enough as JPEG and much smaller for the chat platform.
            buffer = BytesIO()
            out.save(buffer, format="JPEG", quality=90, optimize=True)
        return buffer.getvalue()


def footer(card: Card, label: str, source: str) -> None:
    fonts = card.fonts
    small = Style(11.5, color=MUTED)
    brand = Style(11.5, bold=True)

    def paint(canvas, x, y, width):
        ImageDraw.Draw(canvas).line((x, y, x + width, y), fill=LINE, width=max(1, px(0.5)))
        mid = y + px(17)
        draw_mark(canvas, x, mid - px(8), px(16))
        cursor = draw_text(canvas, fonts, x + px(21), mid, "LenBot", brand, anchor="lm")
        if label:
            draw_text(canvas, fonts, cursor + px(6), mid, label, small, anchor="lm")
        if source:
            text = source
            while measure(fonts, text, small) > width * 0.6 and len(text) > 4:
                text = text[:-2] + "…"
            draw_text(canvas, fonts, x + width, mid, text, small, anchor="rm")

    card.add(px(28), paint, gap=18)
