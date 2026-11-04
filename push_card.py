"""Bilibili push card, ported from the HTML card of astrbot_plugin_asoul: the shared header, the post, then the footer.

One layout carries dynamics, videos, reposts and live sessions. Comments use the template's shorter
form: a line saying where the comment was left, the comment itself, and no footer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import time
from zoneinfo import ZoneInfo

from PIL import Image, ImageOps
import qrcode

from .card_kit import (Card, Fonts, author_header, INK, INK_2, LABEL, LINK, MUTED, PICTURE_FILL, PINK, PINK_LINE, PINK_PALE,
                       PINK_TEXT, QUOTE_BAR, QUOTE_FILL, QUOTE_LINE, RADIUS, Run, SURFACE, Style, chip_width, circle, clip,
                       compact, cover, divider, draw_chip, draw_icon, draw_lines, draw_text, fill, fit, heading, layout,
                       line_height, paragraph, px, qr_block, ramp, ring, rounded, signature, wrap)


@dataclass
class Note:
    """A pink block under the body: the resource a comment belongs to, or a reservation attached to a dynamic."""
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
    pendant: Image.Image | None = None
    uid: str = ""


KIND = {"dynamic": "动态", "video": "新视频", "repost": "转发", "live": "正在直播", "comment": "评论"}
ACTION = {"dynamic": "发布了动态", "video": "投稿了视频", "repost": "转发了动态", "live": "开播了", "comment": "发表了评论"}
BODY = Style(17.5)
BODY_RATIO = 1.66
MAX_BODY_LINES = 36
GRID_GAP = 6
SINGLE_MAX_HEIGHT = 340
CELL_HEIGHT = 155


def when(timestamp: float, zone: str) -> str:
    return datetime.fromtimestamp(timestamp, ZoneInfo(zone)).strftime("%Y-%m-%d %H:%M")


def has_text(runs: list[Run]) -> bool:
    return any(run.image is not None or run.text.strip() for run in runs)


def rich_text(card: Card, runs: list[Run], gap: float) -> None:
    if not has_text(runs):
        return
    lines = clip(card.fonts, layout(card.fonts, runs, BODY, card.inner), BODY, card.inner, MAX_BODY_LINES)
    card.add(len(lines) * line_height(BODY, BODY_RATIO),
             lambda canvas, x, y, w: draw_lines(canvas, card.fonts, lines, x, y, BODY, BODY_RATIO), gap=gap)


def single_picture(image: Image.Image, width: int, limit: int) -> Image.Image:
    """Full width when it fits; a tall picture stays whole on a quiet fill instead of being cropped."""
    height = round(width * image.height / image.width)
    if height <= limit:
        return cover(image, width, height)
    frame = Image.new("RGB", (width, limit), PICTURE_FILL)
    fitted = ImageOps.contain(ImageOps.exif_transpose(image).convert("RGB"), (width, limit), Image.Resampling.LANCZOS)
    frame.paste(fitted, ((width - fitted.width) // 2, 0))
    return frame


def grid_layout(count: int, width: int, cell_height: int) -> tuple[int, int, int]:
    """Columns and cell size: 2 and 4 use two columns, the rest three, as the template's image grid does."""
    columns = 2 if count in (2, 4) else 3
    return columns, (width - px(GRID_GAP) * (columns - 1)) // columns, cell_height


def picture_block(images: list[Image.Image], width: int, single_limit: int, cell_height: int):
    """(height, paint) for one picture or a grid."""
    images = images[:9]
    if len(images) == 1:
        tile = rounded(single_picture(images[0], width, single_limit))
        return tile.height, lambda canvas, x, y: canvas.alpha_composite(tile, (x, y))
    columns, cell_w, cell_h = grid_layout(len(images), width, cell_height)
    rows = -(-len(images) // columns)

    def paint(canvas, x, y):
        for index, image in enumerate(images):
            r, c = divmod(index, columns)
            canvas.alpha_composite(rounded(cover(image, cell_w, cell_h)),
                                   (x + c * (cell_w + px(GRID_GAP)), y + r * (cell_h + px(GRID_GAP))))

    return rows * cell_h + (rows - 1) * px(GRID_GAP), paint


def pictures(card: Card, post: Post) -> None:
    images = [post.cover] if post.kind in ("video", "live") and post.cover is not None else post.images
    if not images:
        return
    height, paint = picture_block(images, card.inner, px(SINGLE_MAX_HEIGHT), px(CELL_HEIGHT))

    def draw(canvas, x, y, width):
        paint(canvas, x, y)
        if post.badge:
            style = Style(13, weight=700, color=SURFACE)
            w = chip_width(card.fonts, post.badge, style, 9)
            draw_chip(canvas, card.fonts, x + width - w - px(10), y + height - px(34), post.badge, SURFACE, INK, style=style,
                      pad_x=9, height=24)

    card.add(height, draw, gap=17)


def title_block(card: Card, post: Post) -> None:
    fonts = card.fonts
    style = Style(19.5, weight=800)
    lines = paragraph(fonts, post.title, style, card.inner, 3)
    if lines:
        card.add(len(lines) * line_height(style, 1.38),
                 lambda canvas, x, y, w: draw_lines(canvas, fonts, lines, x, y, style, 1.38), gap=26)
    if post.meta:
        meta = Style(16, color=INK_2)
        card.add(px(26), lambda canvas, x, y, w: draw_text(canvas, fonts, x, y + px(13), post.meta, meta, anchor="lm"), gap=8)


def quoted(card: Card, post: Post) -> None:
    """A repost keeps the original inside a gray block with a pink bar, under a small kicker."""
    fonts = card.fonts
    pad_left, pad = px(19), px(16)
    inner = card.inner - pad_left - pad
    avatar_size = px(23)
    title_style = Style(15, weight=750, color="#34343d")
    body = Style(14.5, color=INK_2)
    title = paragraph(fonts, post.title, title_style, inner, 2)
    lines = clip(fonts, layout(fonts, post.runs, body, inner), body, inner, MAX_BODY_LINES // 2) if has_text(post.runs) else []
    block = picture_block(post.images, inner, px(310), px(110)) if post.images else None
    title_h = len(title) * line_height(title_style, 1.45)
    body_h = len(lines) * line_height(body, 1.62)
    height = (pad + px(16) + px(9) + avatar_size + (px(10) + title_h if title else 0) + (px(7) + body_h if lines else 0)
              + (px(11) + block[0] if block else 0) + pad)

    def paint(canvas, x, y, width):
        box = (x, y, x + width, y + height)
        fill(canvas, box, px(RADIUS), QUOTE_FILL)
        ring(canvas, box, px(RADIUS), QUOTE_LINE, max(1, px(0.5)))
        bar_w = px(3.5)
        canvas.paste(ramp((bar_w, height - 2 * px(RADIUS)), QUOTE_BAR, vertical=True), (x, y + px(RADIUS)))
        draw_text(canvas, fonts, x + pad_left, y + pad + px(7), "转发内容", Style(12.5, weight=800, color=LABEL), anchor="lm")
        top = y + pad + px(16) + px(9)
        tx = x + pad_left
        if post.avatar is not None:
            canvas.alpha_composite(circle(post.avatar, avatar_size), (tx, top))
            tx += avatar_size + px(7)
        author_style = Style(14.5, weight=800, color=PINK_TEXT)
        right = draw_text(canvas, fonts, tx, top + avatar_size // 2, "@" + fit(fonts, post.author, author_style, inner // 2),
                          author_style, anchor="lm")
        if post.published:
            draw_text(canvas, fonts, right + px(8), top + avatar_size // 2, when(post.published, post.timezone),
                      Style(12.5, color=MUTED), anchor="lm")
        cy = top + avatar_size
        if title:
            cy = draw_lines(canvas, fonts, title, x + pad_left, cy + px(10), title_style, 1.45)
        if lines:
            cy = draw_lines(canvas, fonts, lines, x + pad_left, cy + px(7), body, 1.62)
        if block:
            block[1](canvas, x + pad_left, cy + px(11))

    card.add(height, paint, gap=17)


def reservation(card: Card, item: Note) -> None:
    """The template's additional block: a title with a muted line under it."""
    fonts = card.fonts
    pad = px(13)
    title_style = Style(15.5, weight=700)
    lines = wrap(fonts, item.title, title_style, card.inner - 2 * pad, max_lines=2) if item.title else []
    step = line_height(title_style, 1.4)
    height = 2 * pad + len(lines) * step + px(4) + px(16)

    def paint(canvas, x, y, width):
        box = (x, y, x + width, y + height)
        fill(canvas, box, px(RADIUS), PINK_PALE)
        ring(canvas, box, px(RADIUS), PINK_LINE, max(1, px(0.5)))
        ty = y + pad
        for text in lines:
            draw_text(canvas, fonts, x + pad, ty + step // 2, text, title_style, anchor="lm")
            ty += step
        draw_text(canvas, fonts, x + pad, ty + px(12), item.label, Style(13, color=MUTED), anchor="lm")

    card.add(height, paint, gap=17)


def comment_context(card: Card, post: Post) -> None:
    """Where the comment was left, the first thing under the header of a comment card."""
    fonts = card.fonts
    pad = px(12)
    action = post.action or ACTION["comment"]
    style = Style(14, color="#775e68")
    note = post.note
    where = f"在{note.label}" + (f"《{note.title}》" if note.title else "") + "下" if note else ""
    lines = paragraph(fonts, f"{action} · {where}" if where else action, style, card.inner - 2 * pad, 3)
    height = 2 * pad + len(lines) * line_height(style, 1.55)

    def paint(canvas, x, y, width):
        box = (x, y, x + width, y + height)
        fill(canvas, box, px(RADIUS), PINK_PALE)
        ring(canvas, box, px(RADIUS), PINK_LINE, max(1, px(0.5)))
        draw_lines(canvas, fonts, lines, x + pad, y + pad, style, 1.55)

    card.add(height, paint, gap=19)


def stats(card: Card, values: dict) -> None:
    items = [(icon, label, values[key]) for key, icon, label in (
        ("play", "play", "播放"), ("like", "heart", "点赞"), ("comment", "comment", "评论"), ("forward", "forward", "分享"))
        if key in values]
    if not items:
        return
    fonts = card.fonts
    heading(card, "本条内容", 25)
    height = px(20)
    style = Style(14.5, color="#686873")

    def paint(canvas, x, y, width):
        cursor = x
        middle = y + height // 2
        for icon, label, value in items:
            draw_icon(canvas, icon, cursor, middle - px(8), px(16), "#62626c")
            cursor = draw_text(canvas, fonts, cursor + px(22), middle, f"{compact(value)} {label}", style, anchor="lm") + px(25)

    card.add(height, paint, gap=8)
    divider(card, 16)


def provenance(card: Card, post: Post) -> None:
    """When the card was made and where the post lives."""
    fonts = card.fonts
    stamp = Style(13, color=MUTED)

    def paint(canvas, x, y, width):
        made = datetime.fromtimestamp(time.time(), ZoneInfo(post.timezone)).strftime("%Y-%m-%d %H:%M:%S")
        draw_text(canvas, fonts, x, y + px(8), f"图片生成于：{made}", stamp, anchor="lm")
        if post.url:
            draw_text(canvas, fonts, x, y + px(30), fit(fonts, post.url, Style(13, color=LINK), width), Style(13, color=LINK),
                      anchor="lm")

    card.add(px(40 if post.url else 16), paint, gap=13)


def profile(post: Post):
    """The left side of the footer: who posted this."""
    def paint(canvas, x, y, width, height, fonts):
        size = px(56)
        top = y + (height - size) // 2
        if post.avatar is not None:
            canvas.alpha_composite(circle(post.avatar, size), (x, top))
        else:
            fill(canvas, (x, top, x + size, top + size), size // 2, PINK_LINE)
        tx = x + size + px(11)
        room = width - size - px(11)
        draw_text(canvas, fonts, tx, top + px(7), "UP资料", Style(12.5, weight=800, color=LABEL), anchor="lm")
        name = Style(17, weight=800, color=PINK)
        draw_text(canvas, fonts, tx, top + px(28), fit(fonts, post.author, name, room), name, anchor="lm")
        if post.uid:
            draw_text(canvas, fonts, tx, top + px(49), f"UID: {post.uid}", Style(12.5, color=MUTED), anchor="lm")

    return paint


def qr_image(url: str) -> Image.Image:
    code = qrcode.QRCode(box_size=4, border=1)
    code.add_data(url if "://" in url else f"https://{url}")
    code.make(fit=True)
    return code.make_image(fill_color="#242424", back_color=SURFACE).convert("RGB")


def render_post(post: Post, fonts: Fonts) -> bytes:
    comment = post.kind == "comment"
    card = Card(fonts, strip=5.5 if comment else 7)
    live = post.kind == "live"
    published = when(post.published, post.timezone) if post.published else post.action or ACTION[post.kind]
    author_header(card, post.author, published, avatar=post.avatar, pendant=post.pendant,
                  kind="" if comment else KIND[post.kind], kind_dot=live)
    if comment:
        comment_context(card, post)
        heading(card, "评论内容", 17)
        rich_text(card, post.runs, 8)
        signature(card)
        return card.render()
    title_block(card, post)
    rich_text(card, post.runs, 12 if post.title else 26)
    pictures(card, post)
    if post.quoted is not None:
        quoted(card, post.quoted)
    if post.note is not None:
        reservation(card, post.note)
    stats(card, post.stats)
    provenance(card, post)
    if post.url:
        draw_profile = profile(post)
        qr_block(card, lambda canvas, x, y, width, height: draw_profile(canvas, x, y, width, height, fonts), px(92),
                 qr_image(post.url))
    signature(card)
    return card.render()
