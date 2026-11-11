# -*- coding: utf-8 -*-
"""
把文字写进纸上。

为什么不直接用矩形：这张底图里鲸鲸的两只手是从左下、右下伸上来抓着纸的，
手指把纸的下半部分两边挡住了。用矩形框的话，长句最后几行就会压在手指上。
所以这里按「行」来定可用宽度——配置里给一张表：

    rows = [(y, 左边界, 右边界), ...]

越往下两边收得越窄，排版时每一行都用它自己那一层的宽度换行，
文字自然绕开手指，也不会被手挡掉半个字。

渲染出来是 PIL.Image（RGBA）。
"""

import os
from typing import List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

# 不能出现在行首的标点（中文排版的「行首禁则」）
NO_LINE_START = "，。！？、；：）】」』…—～,.!?;:)]}%"
# 不能出现在行尾的（开引号/开括号）
NO_LINE_END = "（【「『([{"

# 一行最多几个字：≤8 个字永远只有一行（宁可把字缩小），第 9 个字才换行
MAX_CHARS_PER_LINE = 8
# 按 8 字一行硬排时，字号掉到这个值以下就没法看了，改回「按宽度自动排」
MIN_FONT_WHEN_CAPPED = 15
# 试字号时最小试到这里（再小就不当候选了）
MIN_FONT_SCAN = 8

_font_cache = {}


def load_font(font_path: Optional[str], size: int) -> ImageFont.FreeTypeFont:
    key = (font_path, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(font_path, size)
    return _font_cache[key]


# ------------------------------------------------------------
#  文字区：给定 y，插值出这一行能用的左右边界
# ------------------------------------------------------------
def rows_slice(rows: Sequence[Tuple[float, float, float]], y: float) -> Tuple[float, float]:
    if y <= rows[0][0]:
        return rows[0][1], rows[0][2]
    if y >= rows[-1][0]:
        return rows[-1][1], rows[-1][2]
    for i in range(len(rows) - 1):
        y0, l0, r0 = rows[i]
        y1, l1, r1 = rows[i + 1]
        if y0 <= y <= y1:
            t = (y - y0) / max(1e-6, y1 - y0)
            return l0 + (l1 - l0) * t, r0 + (r1 - r0) * t
    return rows[-1][1], rows[-1][2]


# ------------------------------------------------------------
#  每个字的颜色：中括号【】 / [] 里的字换成括号色
# ------------------------------------------------------------
def colorize(text: str, color, bracket_color) -> List[Tuple[str, tuple]]:
    out = []
    depth = 0
    for ch in text:
        if ch in "【[":
            depth += 1
            out.append((ch, bracket_color))
        elif ch in "】]":
            out.append((ch, bracket_color))
            depth = max(0, depth - 1)
        else:
            out.append((ch, bracket_color if depth > 0 else color))
    return out


# ------------------------------------------------------------
#  换行：第 i 行用第 i 个宽度上限
# ------------------------------------------------------------
def wrap(chars, widths: Sequence[float], max_chars: Optional[int] = None) -> List[list]:
    def limit(i):
        return widths[min(i, len(widths) - 1)]

    lines, cur, cur_w, li, i = [], [], 0.0, 0, 0
    while i < len(chars):
        ch, col, w = chars[i]

        if ch == "\n":
            lines.append(cur)
            cur, cur_w = [], 0.0
            li += 1
            i += 1
            continue

        # 一行的字数到顶了（≤8 字一行），不管还放不放得下都换行
        if cur and max_chars and len(cur) >= max_chars:
            lines.append(cur)
            cur, cur_w = [], 0.0
            li += 1
            continue

        if cur and cur_w + w > limit(li):
            # 行首禁则：标点不放行首，宁可这行稍微挤一点
            if ch in NO_LINE_START and cur_w + w <= limit(li) * 1.1:
                cur.append(chars[i])
                lines.append(cur)
                cur, cur_w = [], 0.0
                li += 1
                i += 1
                continue

            # 英文不拦腰切断：回退到最近的非字母处
            if ch.isascii() and ch.isalnum():
                j = len(cur) - 1
                while j >= 0 and cur[j][0].isascii() and cur[j][0].isalnum():
                    j -= 1
                if j >= 0 and j + 1 < len(cur):
                    carry = cur[j + 1:]
                    lines.append(cur[: j + 1])
                    cur = carry
                    cur_w = sum(c[2] for c in cur)
                    li += 1
                    continue

            lines.append(cur)
            cur, cur_w = [], 0.0
            li += 1
            continue

        cur.append(chars[i])
        cur_w += w
        i += 1

    if cur:
        lines.append(cur)
    return lines


# ------------------------------------------------------------
#  把字平均切成分行数相同的几段（贪心换行常常留下一个很短的尾巴，
#  比如 5/5/2，看着难受；切不平、或者某一行超宽就返回 None，退回贪心）
# ------------------------------------------------------------
def _balanced_split(chars, widths, n, max_chars=None):
    total = len(chars)
    if n < 2 or total < n:
        return None
    if any(c[0] == "\n" for c in chars):
        return None
    if max_chars and total > n * max_chars:
        return None

    base, rem = divmod(total, n)
    counts = [base + (1 if i < rem else 0) for i in range(n)]

    # 行首禁则：标点不许出现在行首——把上一行的末字挪过来一起带到下一行
    for i in range(1, n):
        start = sum(counts[:i])
        if start >= total:
            return None
        if chars[start][0] in NO_LINE_START:
            if counts[i - 1] <= 1:
                return None
            counts[i - 1] -= 1
            counts[i] += 1

    lines, pos = [], 0
    for i, k in enumerate(counts):
        seg = chars[pos:pos + k]
        if not seg or sum(c[2] for c in seg) > widths[min(i, len(widths) - 1)] + 0.5:
            return None
        if seg[-1][0] in NO_LINE_END:
            return None
        lines.append(seg)
        pos += k
    return lines if pos == total else None


# ------------------------------------------------------------
#  排版：二分找最大的字号，让每一行都不越界
# ------------------------------------------------------------
def _try_layout(rows, chars, font, padding, line_spacing, valign, max_chars=None):
    ascent, descent = font.getmetrics()
    line_h = int((ascent + descent) * (1 + line_spacing))

    top_y = rows[0][0]
    bot_y = rows[-1][0]

    total = sum(1 for c in chars if c[0] != "\n")
    # 按「每行最多 max_chars 个字」算出来至少要有几行：≤8 字 → 1 行，第 9 个字才 2 行
    need = max(1, -(-total // max_chars)) if max_chars else 0

    n = max(1, need) if need else 1
    for _ in range(10):
        block_h = n * line_h
        block_top = top_y if valign == "top" else (top_y + bot_y) / 2 - block_h / 2

        widths = []
        for i in range(n):
            y = block_top + i * line_h + line_h / 2
            left, right = rows_slice(rows, y)
            widths.append(max(8.0, (right - left) - 2 * padding))

        lines = wrap(chars, widths, max_chars)
        if len(lines) == n:
            break
        n = len(lines)

    # 行数超过「8 字一行」允许的行数 ⇒ 这个字号太大，换小一号
    if need and len(lines) > need:
        return None
    if max_chars and any(len(line) > max_chars for line in lines):
        return None

    # 行数定了，先把每行字数排匀；排不匀（或超宽）就退回上面贪心的结果
    n = len(lines)
    if n >= 2:
        even = _balanced_split(chars, widths, n, max_chars)
        if even is not None:
            lines = even

    # 别让最后一行只剩一个字（孤字很难看）：从上一行挪一个字下来
    if len(lines) >= 2 and len(lines[-1]) == 1 and len(lines[-2]) >= 3:
        lines[-1].insert(0, lines[-2].pop())

    block_h = len(lines) * line_h
    block_top = top_y if valign == "top" else (top_y + bot_y) / 2 - block_h / 2
    if block_top < top_y - 2 or block_top + block_h > bot_y + 2:
        return None

    for i, line in enumerate(lines):
        y = block_top + i * line_h + line_h / 2
        left, right = rows_slice(rows, y)
        if sum(c[2] for c in line) > (right - left) - 2 * padding + 2:
            return None

    return lines, line_h, block_top


def _search_layout(rows, cached, font_path, max_font_height, padding, line_spacing, valign, max_chars):
    """二分找最大的能排下的字号。max_chars=None 表示「按宽度自动换行」。"""
    lo, hi = 1, max(1, int(max_font_height))
    best = None
    while lo <= hi:
        mid = (lo + hi) // 2
        font = load_font(font_path, mid)
        chars = [(ch, col, font.getlength(ch)) for ch, col in cached]
        got = _try_layout(rows, chars, font, padding, line_spacing, valign, max_chars)
        if got:
            best = (got[0], got[1], got[2], mid)
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _best_layout(rows, cached, font_path, max_font_height, padding, line_spacing, valign, max_chars):
    """先按「每行最多 8 字」排；字号被挤得太小（或根本排不下）就退回按宽度自动排。"""
    best = _search_layout(rows, cached, font_path, max_font_height, padding,
                          line_spacing, valign, max_chars)
    if max_chars:
        if best is None or best[3] < MIN_FONT_WHEN_CAPPED:
            alt = _search_layout(rows, cached, font_path, max_font_height, padding,
                                 line_spacing, valign, None)
            if alt is not None and (best is None or alt[3] > best[3]):
                best = alt
    return best


def _flow_placements(pages, chars, font, padding, line_spacing, max_chars=None):
    """把字一行行铺满 pages（每页一串 rows）：左页写完再写右页。

    返回 [(page_index, y, line_chars), ...]；放不下返回 None。
    """
    ascent, descent = font.getmetrics()
    line_h = int((ascent + descent) * (1 + line_spacing))
    total = len(chars)
    i = 0
    out = []
    for pi, rows in enumerate(pages):
        top_y, bot_y = rows[0][0], rows[-1][0]
        cap = max(1, int((bot_y - top_y) // line_h))
        for k in range(cap):
            if i >= total:
                break
            y = top_y + k * line_h + line_h / 2
            left, right = rows_slice(rows, y)
            w = max(8.0, (right - left) - 2 * padding)
            j, width, n = i, 0.0, 0
            while j < total:
                ch, _col, cw = chars[j]
                if ch == "\n":
                    break
                if n and max_chars is not None and n >= max_chars:
                    break
                if n and width + cw > w:
                    break
                width += cw
                j += 1
                n += 1
            # 避头：下一行行首是标点时，把这个标点挤进本行（允许略微超宽）
            if j < total and j > i and chars[j][0] != "\n" and chars[j][0] in NO_LINE_START:
                extra = chars[j][2]
                if width + extra <= w * 1.25 and (max_chars is None or n < max_chars):
                    width += extra
                    j += 1
                    n += 1
            if j == i:  # 一个字都放不下
                return None
            out.append((pi, y, chars[i:j]))
            i = j
            if i < total and chars[i][0] == "\n":
                i += 1
    if i < total:
        return None
    out = _fix_widow(pages, out, padding)
    return out, line_h


def _fix_widow(pages, out, padding):
    """末行只剩一个字、上一行还有 3 个以上：把上一行末字挪下来，别留孤字。"""
    if len(out) < 2:
        return out
    pi, y, last = out[-1]
    ppi, py, prev = out[-2]
    if len(last) != 1 or len(prev) < 3:
        return out
    moved = prev[-1]
    left, right = rows_slice(pages[pi], y)
    width = sum(c[2] for c in last) + moved[2]
    if width > (right - left) - 2 * padding:
        return out
    out[-2] = (ppi, py, prev[:-1])
    out[-1] = (pi, y, [moved] + list(last))
    return out


def _search_pages(pages, cached, font_path, max_font_height, padding, line_spacing, max_chars):
    lo, hi = 1, max(1, int(max_font_height))
    best = None
    while lo <= hi:
        mid = (lo + hi) // 2
        font = load_font(font_path, mid)
        chars = [(ch, col, font.getlength(ch)) for ch, col in cached]
        got = _flow_placements(pages, chars, font, padding, line_spacing, max_chars)
        if got:
            best = (got[0], got[1], mid)
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _page_usage(placements):
    """每一页各写了几行。"""
    used = {}
    for pi, _y, _chars in placements[0]:
        used[pi] = used.get(pi, 0) + 1
    return used


def _spill_is_ugly(placements):
    """翻页后只剩一行孤零零的字，看着很别扭——这种字号不算数。"""
    used = _page_usage(placements)
    if len(used) <= 1:
        return False
    return used[max(used)] < 2


def _scan_pages(pages, cached, font_path, max_font_height, padding, line_spacing, max_chars):
    """从大往小扫，取第一个「排得好看」的字号（两页字号一定一致）。"""
    for size in range(max(1, int(max_font_height)), MIN_FONT_SCAN - 1, -1):
        font = load_font(font_path, size)
        chars = [(ch, col, font.getlength(ch)) for ch, col in cached]
        got = _flow_placements(pages, chars, font, padding, line_spacing, max_chars)
        if got and not _spill_is_ugly(got):
            return (got[0], got[1], size)
    return None


def _best_pages(pages, cached, font_path, max_font_height, padding, line_spacing, max_chars):
    best = _scan_pages(pages, cached, font_path, max_font_height, padding, line_spacing, max_chars)
    if best is None:
        # 最后兜底：不看「孤行」，直接找能塞下的最大字号
        best = _search_pages(pages, cached, font_path, max_font_height, padding, line_spacing, max_chars)
    if max_chars and (best is None or best[2] < MIN_FONT_WHEN_CAPPED):
        alt = _scan_pages(pages, cached, font_path, max_font_height, padding, line_spacing, None)
        if alt is None:
            alt = _search_pages(pages, cached, font_path, max_font_height, padding, line_spacing, None)
        if alt is not None and (best is None or alt[2] > best[2]):
            best = alt
    return best


def fit_font_size(rows, text, font_path, max_font_height=76, line_spacing=0.12,
                  padding=4, valign="middle", bracket_color=(128, 0, 128), color=(0, 0, 0),
                  max_chars=MAX_CHARS_PER_LINE):
    """返回 (字号, 行数)；塞不下就返回最小的那个。"""
    cached = colorize(text, color, bracket_color)
    best = _best_layout(rows, cached, font_path, max_font_height, padding,
                        line_spacing, valign, max_chars)
    if best is None:
        return 1, 1
    return best[3], len(best[0])


def render_text_on_paper(
    base_image,
    rows,
    text: str,
    font_path: str,
    color=(34, 38, 56),
    bracket_color=(128, 0, 128),
    max_font_height: int = 76,
    alpha: float = 0.85,
    line_spacing: float = 0.12,
    padding: int = 4,
    valign: str = "middle",
    max_chars: int = MAX_CHARS_PER_LINE,
    pages=None,
) -> Image.Image:
    base = (
        Image.open(base_image).convert("RGBA")
        if isinstance(base_image, (str, os.PathLike))
        else base_image.copy()
    )
    text = (text or "").strip()
    if not text:
        return base

    cached = colorize(text, color, bracket_color)

    # 书页模式：先写左页，写满再接着写右页
    if pages:
        got = _best_pages(pages, cached, font_path, max_font_height, padding,
                          line_spacing, max_chars)
        if got is None:
            return base
        placements, line_h, size = got
        font = load_font(font_path, size)
        ascent, descent = font.getmetrics()
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        for pi, y, line in placements:
            left, right = rows_slice(pages[pi], y)
            line_w = sum(c[2] for c in line)
            x = (left + right) / 2 - line_w / 2
            y_top = y - (ascent + descent) / 2
            for ch, col, w in line:
                ld.text((x, y_top), ch, font=font, fill=tuple(col) + (255,), anchor="la")
                x += w
        if alpha < 1.0:
            a = layer.getchannel("A").point(lambda v: int(v * alpha))
            layer.putalpha(a)
        base.alpha_composite(layer)
        return base

    best = _best_layout(rows, cached, font_path, max_font_height, padding,
                        line_spacing, valign, max_chars)

    if best is None:
        return base

    lines, line_h, block_top, size = best
    font = load_font(font_path, size)
    ascent, descent = font.getmetrics()

    # 先画在透明图层上，再整体按 alpha 压到底图，字就是半透明的墨
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    for i, line in enumerate(lines):
        y = block_top + i * line_h + line_h / 2
        left, right = rows_slice(rows, y)
        line_w = sum(c[2] for c in line)
        x = (left + right) / 2 - line_w / 2
        y_top = y - (ascent + descent) / 2
        for ch, col, w in line:
            ld.text((x, y_top), ch, font=font, fill=tuple(col) + (255,), anchor="la")
            x += w

    if alpha < 1.0:
        a = layer.getchannel("A").point(lambda v: int(v * alpha))
        layer.putalpha(a)
    base.alpha_composite(layer)
    return base


def png_bytes(image: Image.Image) -> bytes:
    from io import BytesIO

    bio = BytesIO()
    image.save(bio, "PNG")
    return bio.getvalue()
