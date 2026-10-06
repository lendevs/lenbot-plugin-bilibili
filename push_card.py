"""Bilibili push card: one layout for dynamics, videos, reposts, comments and live sessions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw

from .card_kit import (Card, Fonts, Run, Style, HOVER, MUTED, PAGE, PRIMARY, SUCCESS, SUCCESS_BG, TRACK,
                       chip_width, circle, compact, cover, draw_chip, draw_lines, draw_text, footer, layout, line_height,
                       measure, px, rounded, wrap)


@dataclass
class Note:
    """A gray block under the body: the resource a comment belongs to, or a reservation attached to a dynamic."""
    label: str
    title: str


@dataclass
class Post:
    kind: str                       # dynamic | video | repost | live | comment
    author: str
    avatar: Image.Image | None
    published: float
    runs: list[Run] = field(default_factory=list)
    images: list[Image.Image] = field(default_factory=list)
    title: str = ""                 # video or live title
    cover: Image.Image | None = None
    badge: str = ""                 # video duration
    meta: str = ""                  # live area
    stats: dict = field(default_factory=dict)
    quoted: "Post | None" = None
    note: Note | None = None
    action: str = ""                # overrides the default verb, e.g. a reply instead of a comment
    url: str = ""
    timezone: str = "Asia/Shanghai"


KIND = {"dynamic": "动态", "video": "视频", "repost": "转发", "live": "直播中", "comment": "评论"}
ACTION = {"dynamic": "发布了动态", "video": "投稿了视频", "repost": "转发了动态", "live": "开播了", "comment": "发表了评论"}
BODY = Style(15.5)
MAX_BODY_LINES = 36


def when(timestamp: float, zone: str) -> str:
    moment = datetime.fromtimestamp(timestamp, ZoneInfo(zone))
    return f"{moment.month}月{moment.day}日 {moment:%H:%M}"


def header(card: Card, post: Post) -> None:
    fonts = card.fonts
    size = px(44)

    def paint(canvas, x, y, width):
        if post.avatar is not None:
            canvas.alpha_composite(circle(post.avatar, size), (x, y))
        else:
            ImageDraw.Draw(canvas).ellipse((x, y, x + size, y + size), fill=TRACK)
        live = post.kind == "live"
        chip_w = chip_width(fonts, KIND[post.kind], dot=live)
        tx = x + size + px(12)
        name_style = Style(16, bold=True)
        name = wrap(fonts, post.author, name_style, width - (tx - x) - chip_w - px(12), max_lines=1)[0]
        draw_text(canvas, fonts, tx, y + px(3), name, name_style)
        action = post.action or ACTION[post.kind]
        subtitle = f"{action} · {when(post.published, post.timezone)}" if post.published else action
        draw_text(canvas, fonts, tx, y + px(26), subtitle, Style(12.5, color=MUTED))
        draw_chip(canvas, fonts, x + width - chip_w, y + px(12), KIND[post.kind],
                  SUCCESS if live else MUTED, SUCCESS_BG if live else HOVER, dot=SUCCESS if live else None)

    card.add(size, paint, gap=0)


def clip(fonts: Fonts, lines: list, style: Style, width: int, limit: int) -> list:
    """Keep at most ``limit`` lines; the last kept line ends with an ellipsis."""
    if len(lines) <= limit:
        return lines
    lines = [list(line) for line in lines[:limit]]
    ellipsis = measure(fonts, "…", style)
    last = lines[-1]
    while last and sum(unit[2] for unit in last) + ellipsis > width:
        last.pop()
    font = fonts.pick("…", style.size, style.bold)
    last.append(("text", "…", font.getlength("…"), font))
    return lines


def rich_text(card: Card, runs: list[Run]) -> None:
    if not any(run.image is not None or run.text.strip() for run in runs):
        return
    lines = clip(card.fonts, layout(card.fonts, runs, BODY, card.inner), BODY, card.inner, MAX_BODY_LINES)
    card.add(len(lines) * line_height(BODY), lambda canvas, x, y, w: draw_lines(canvas, card.fonts, lines, x, y, BODY))


def grid(count: int, width: int) -> tuple[int, int, int]:
    """Columns and cell size; one image keeps a 4:3 frame, 2 and 4 use two columns, the rest three."""
    gap = px(4)
    if count == 1:
        return 1, width, round(width * 3 / 4)
    columns = 2 if count in (2, 4) else 3
    cell = (width - gap * (columns - 1)) // columns
    return columns, cell, cell


def paint_grid(canvas, images, x, y, columns, cell_w, cell_h, radius=8):
    for index, image in enumerate(images):
        r, c = divmod(index, columns)
        canvas.alpha_composite(rounded(cover(image, cell_w, cell_h), radius),
                               (x + c * (cell_w + px(4)), y + r * (cell_h + px(4))))


def image_grid(card: Card, images: list[Image.Image]) -> None:
    if not images:
        return
    images = images[:9]
    columns, cell_w, cell_h = grid(len(images), card.inner)
    rows = -(-len(images) // columns)
    card.add(rows * cell_h + (rows - 1) * px(4),
             lambda canvas, x, y, w: paint_grid(canvas, images, x, y, columns, cell_w, cell_h))


def media(card: Card, post: Post) -> None:
    fonts = card.fonts
    width = card.inner
    frame = round(width * 9 / 16)
    title_style = Style(16, bold=True)
    lines = wrap(fonts, post.title, title_style, width, max_lines=2) if post.title else []
    step = px(25)
    height = frame + (px(12) if lines else 0) + len(lines) * step + (px(20) if post.meta else 0)

    def paint(canvas, x, y, _):
        if post.cover is not None:
            canvas.alpha_composite(rounded(cover(post.cover, width, frame), 8), (x, y))
        else:
            ImageDraw.Draw(canvas).rounded_rectangle((x, y, x + width, y + frame), radius=px(8), fill=TRACK)
        if post.badge:
            style = Style(12, bold=True, color="#ffffff")
            w = chip_width(fonts, post.badge, style)
            overlay = Image.new("RGBA", (w, px(22)), (0, 0, 0, 0))
            ImageDraw.Draw(overlay).rounded_rectangle((0, 0, w - 1, px(22) - 1), radius=px(6), fill=(20, 20, 30, 165))
            draw_text(overlay, fonts, w / 2, px(11), post.badge, style, anchor="mm")
            canvas.alpha_composite(overlay, (x + width - w - px(10), y + frame - px(32)))
        ty = y + frame + px(12)
        for text in lines:
            draw_text(canvas, fonts, x, ty, text, title_style)
            ty += step
        if post.meta:
            draw_text(canvas, fonts, x, ty + px(2), post.meta, Style(12.5, color=MUTED))

    card.add(height, paint)


def quoted(card: Card, post: Post) -> None:
    """A repost keeps the original inside a gray block; the same pieces, slightly smaller."""
    fonts = card.fonts
    pad = px(14)
    inner = card.inner - 2 * pad
    body = Style(14.5)
    runs = ([Run(post.title + "\n")] if post.title else []) + post.runs
    has_text = any(r.image is not None or r.text.strip() for r in runs)
    lines = clip(fonts, layout(fonts, runs, body, inner), body, inner, MAX_BODY_LINES // 2) if has_text else []
    images = post.images[:9]
    columns, cell_w, cell_h = grid(len(images), inner) if images else (1, 0, 0)
    if len(images) == 1:
        cell_w = cell_h = inner // 2
    rows = -(-len(images) // columns) if images else 0
    grid_h = rows * cell_h + max(0, rows - 1) * px(4)
    height = (pad + px(20) + (px(6) + len(lines) * line_height(body) if lines else 0)
              + (px(10) + grid_h if images else 0) + pad)

    def paint(canvas, x, y, width):
        ImageDraw.Draw(canvas).rounded_rectangle((x, y, x + width, y + height), radius=px(8), fill=PAGE)
        right = draw_text(canvas, fonts, x + pad, y + pad, "@" + post.author, Style(13.5, bold=True, color=PRIMARY))
        if post.published:
            draw_text(canvas, fonts, right + px(8), y + pad + px(1), when(post.published, post.timezone),
                      Style(12, color=MUTED))
        cy = y + pad + px(20)
        if lines:
            cy = draw_lines(canvas, fonts, lines, x + pad, cy + px(6), body)
        if images:
            paint_grid(canvas, images, x + pad, cy + px(10), columns, cell_w, cell_h, radius=6)

    card.add(height, paint)


def note(card: Card, item: Note) -> None:
    fonts = card.fonts
    pad = px(12)
    title_style = Style(14, bold=True)
    lines = wrap(fonts, item.title, title_style, card.inner - 2 * pad, max_lines=2) if item.title else []
    step = px(22)
    height = pad + px(17) + (px(4) + len(lines) * step if lines else 0) + pad

    def paint(canvas, x, y, width):
        ImageDraw.Draw(canvas).rounded_rectangle((x, y, x + width, y + height), radius=px(8), fill=PAGE)
        draw_text(canvas, fonts, x + pad, y + pad, item.label, Style(12.5, color=MUTED))
        ty = y + pad + px(21)
        for text in lines:
            draw_text(canvas, fonts, x + pad, ty, text, title_style)
            ty += step

    card.add(height, paint)


def stats(card: Card, values: dict) -> None:
    items = [(label, values[key]) for key, label in (("play", "播放"), ("like", "赞"), ("comment", "评论"), ("forward", "转发"))
             if key in values]
    if not items:
        return

    def paint(canvas, x, y, width):
        cursor = x
        for label, value in items:
            cursor = draw_text(canvas, card.fonts, cursor, y, label, Style(12.5, color=MUTED)) + px(4)
            cursor = draw_text(canvas, card.fonts, cursor, y, compact(value), Style(12.5, bold=True)) + px(16)

    card.add(px(16), paint, gap=12)


def render_post(post: Post, fonts: Fonts) -> bytes:
    card = Card(fonts)
    header(card, post)
    rich_text(card, post.runs)
    if post.kind in ("video", "live"):
        media(card, post)
    image_grid(card, post.images)
    if post.quoted is not None:
        quoted(card, post.quoted)
    if post.note is not None:
        note(card, post.note)
    stats(card, post.stats)
    footer(card, "哔哩哔哩", post.url)
    return card.render()
