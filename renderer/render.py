# -*- coding: utf-8 -*-
"""传话纸渲染器（独立版）。

用法：从 stdin 喂一行 JSON，往 stdout 回一行 JSON。

    {"cards": "cards.json", "role": "鲸鲸", "expr": "#开心#", "text": "今天也要好好吃饭呀", "out": "out.png"}
    -> {"ok": true, "path": "...\\out.png"}

也支持「复用某个传话纸项目」的写法（如果你本地有那套工程，字体、可写区改完立刻生效）：

    {"project": "D:/xx/鲸鲸的传话纸", "role": "鲸鲸", "expr": "#开心#", "text": "...", "out": "..."}

排版全部交给同目录的 paper_text.py：
    rows   逐行宽度表 [(y, 左, 右), ...]——纸上越往下越窄时用这个
    pages  书页流 [[左页 rows], [右页 rows]]——先写满左页再写右页
    quad   四点 [(x,y)*4]——举的是斜着的板子/牌子时用这个，文字跟着板子倾斜
"""
from __future__ import annotations

import json
import os
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from paper_text import render_text_on_paper  # noqa: E402


def _png_result(ok, **kw):
    return {"ok": ok, **kw}


def _quad_render(base, quad, text, font_path, spec, alpha):
    """把文字排在平整画布上，再按四个角贴回去（仿射，字不会一大一小）。"""
    import math

    (x0, y0), (x1, y1), _, (x3, y3) = quad
    width = int(round(math.hypot(x1 - x0, y1 - y0)))
    height = int(round(math.hypot(x3 - x0, y3 - y0)))
    if width < 16 or height < 16:
        raise ValueError("quad 太小：%r" % (quad,))

    pad_x = float(spec.get("pad_x", 0.13))
    pad_y = float(spec.get("pad_y", 0.17))
    left = int(width * pad_x)
    right = int(width * (1 - pad_x))
    # 至少两层：只有一层的话可用高度是 0，排版会一路缩到最小字号
    flat_rows = [(int(height * pad_y), left, right), (int(height * (1 - pad_y)), left, right)]

    flat = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    flat = render_text_on_paper(
        flat,
        flat_rows,
        text,
        font_path,
        color=tuple(spec.get("color", (34, 38, 56))),
        bracket_color=tuple(spec.get("bracket_color", (128, 0, 128))),
        max_font_height=int(spec.get("max_font_height", 96)),
        alpha=alpha,
        line_spacing=float(spec.get("line_spacing", 0.10)),
        padding=int(spec.get("padding", 4)),
        max_chars=int(spec.get("max_chars", 8)),
    )

    # 仿射：PIL 的 AFFINE 要的是「输出像素 → 输入像素」的反向映射，
    # 所以这里解的是 base 坐标回到 flat 坐标 (u,v) 的逆矩阵。
    ux, uy = (x1 - x0) / width, (y1 - y0) / width
    vx, vy = (x3 - x0) / height, (y3 - y0) / height
    det = ux * vy - vx * uy
    if abs(det) < 1e-9:
        raise ValueError("quad 退化成一条线了：%r" % (quad,))
    # [u,v] = M * (p - TL)，M = [[ux,vx],[uy,vy]]^-1
    m00, m01 = vy / det, -vx / det
    m10, m11 = -uy / det, ux / det
    coeffs = (
        m00, m01, -(m00 * x0 + m01 * y0),
        m10, m11, -(m10 * x0 + m11 * y0),
    )
    warped = flat.transform(base.size, Image.AFFINE, coeffs, resample=Image.BICUBIC, fillcolor=(0, 0, 0, 0))
    base.alpha_composite(warped)
    return base


def render_with_cards(payload):
    cards_path = payload["cards"]
    if not os.path.isabs(cards_path):
        cards_path = os.path.join(HERE, cards_path)
    with open(cards_path, "r", encoding="utf-8") as fh:
        cards = json.load(fh)

    role = payload.get("role") or next(iter(cards))
    spec = cards[role]
    expr = payload.get("expr") or "#普通#"
    images = spec.get("images") or {}
    image_rel = images.get(expr) or next(iter(images.values()))
    image_path = image_rel if os.path.isabs(image_rel) else os.path.join(os.path.dirname(cards_path), image_rel)

    font_rel = spec.get("font") or "font.ttf"
    font_path = font_rel if os.path.isabs(font_rel) else os.path.join(os.path.dirname(cards_path), font_rel)

    alpha = float(spec.get("alpha", 0.8))
    text = payload["text"]
    base = Image.open(image_path).convert("RGBA")

    if spec.get("quad"):
        img = _quad_render(base, spec["quad"], text, font_path, spec, alpha)
    else:
        img = render_text_on_paper(
            base,
            spec.get("rows") or [(0, 0, base.width)],
            text,
            font_path,
            color=tuple(spec.get("color", (34, 38, 56))),
            bracket_color=tuple(spec.get("bracket_color", (128, 0, 128))),
            max_font_height=int(spec.get("max_font_height", 76)),
            alpha=alpha,
            line_spacing=float(spec.get("line_spacing", 0.12)),
            padding=int(spec.get("padding", 4)),
            pages=spec.get("pages"),
            max_chars=int(spec.get("max_chars", 8)),
        )
    return img.convert("RGB")


def render_with_project(payload):
    project = payload["project"]
    sys.path.insert(0, project)
    os.chdir(project)
    import main as project_main  # noqa: PLC0415

    project_main.load_state()
    png = project_main.render_text(
        payload.get("role") or "鲸鲸",
        payload.get("expr") or "#普通#",
        payload["text"],
    )
    from io import BytesIO  # noqa: PLC0415

    return Image.open(BytesIO(png)).convert("RGB")


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
        img = render_with_project(payload) if payload.get("project") else render_with_cards(payload)
        out = payload["out"]
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        img.save(out, "PNG")
        print(json.dumps(_png_result(True, path=os.path.abspath(out)), ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps(_png_result(False, error="%s: %s" % (type(exc).__name__, exc)), ensure_ascii=False))


if __name__ == "__main__":
    main()
