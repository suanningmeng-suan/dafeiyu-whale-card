# -*- coding: utf-8 -*-
"""大肥鱼发传话纸 —— AstrBot 插件。

她每要说一句话，先按概率掷骰子；中了就把这句话画成「角色举着牌子/纸」的图，
只发图（字已经写在牌子上），没中就照常打字。

所有可调的东西都在同目录的 config.json 里（第一次运行会自动生成），
不依赖 AstrBot 的配置系统，换 AstrBot 版本也不用改。

渲染交给 renderer/ 里的独立渲染器（自带排版引擎），
或者指向你自己那套「传话纸」工程（config.json 里填 project_dir）。
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

from astrbot import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image, Plain, Record
from astrbot.api.star import Context, Star

PLUGIN_DIR = Path(__file__).resolve().parent
REPO_ROOT = PLUGIN_DIR.parent
CONFIG_FILE = PLUGIN_DIR / "config.json"
LOG_FILE = PLUGIN_DIR / "cards.log.jsonl"
OUT_DIR = Path(os.environ.get("TEMP") or os.path.expanduser("~")) / "whale-card-qq"

DEFAULTS = {
    "enabled": True,
    "rate": 10,              # 百分比：每 100 句话里，大概几张
    "mode": "image",         # image = 只发图；both = 文字和图片都发
    "role": "鲸鲸",           # cards.json / 工程里的角色名
    "max_chars": 28,         # 超过就不画（牌子上塞不下）
    "auto_mood": True,       # 按语气猜心情
    "python": sys.executable,          # 调渲染器用的解释器（要装 Pillow）
    "renderer": "renderer/render.py",  # 相对仓库根目录
    "cards": "renderer/cards.json",    # 独立渲染模式用
    "project_dir": ""                  # 非空则改用「传话纸工程」渲染
}

URL_RE = re.compile(
    r"(https?://|www\.|[a-zA-Z0-9-]+\.(com|cn|net|org|io|top|xyz|me|tv|cc|app|dev)([/?]|\b))",
    re.I,
)

MOOD_TABLE = [
    (r"[!！]{1,}", "#开心#"),
    (r"[?？]", "#不解#"),
    (r"(……|\.\.\.|。。。)", "#无语#"),
    (r"[~～]", "#微笑#"),
    (r"(哈哈|开心|高兴|太好了|好耶|棒|喜欢|爱了|笑死|嘿嘿|可爱|贴贴|抱抱)", "#开心#"),
    (r"(难过|伤心|呜呜|哭|委屈|舍不得|想哭|心疼|孤单)", "#哭泣#"),
    (r"(生气|气死|烦|讨厌|滚|无语了|服了|离谱|过分)", "#生气#"),
    (r"(不懂|为什么|怎么会|疑惑|奇怪|啥|啥啊|哪|确定吗)", "#不解#"),
    (r"(害羞|脸红|不好意思|讨厌啦|别这样|心跳)", "#脸红#"),
    (r"(震惊|居然|没想到|竟然|真的假的|天哪|啊这)", "#意外#"),
    (r"(微笑|嗯嗯|好的呀|晚安|辛苦|加油|慢慢来|陪你|我陪着)", "#微笑#"),
    (r"(算了|随便|哦|行吧|呵呵|就这)", "#无语#"),
    (r"(恨|死|永远|一直|只能|别走|别离开)", "#病娇#"),
]

FALLBACK_MOODS = (["#微笑#", "#开心#", "#不解#", "#无语#", "#普通#"], [3, 2, 2, 2, 1])


def load_config():
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text("utf-8")))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[whale-card] config.json 读不动，用默认值：%s", exc)
    else:
        try:
            CONFIG_FILE.write_text(json.dumps(DEFAULTS, ensure_ascii=False, indent=2), "utf-8")
        except Exception:  # noqa: BLE001
            pass
    return cfg


def append_log(entry):
    try:
        row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()), **entry}
        lines = LOG_FILE.read_text("utf-8").splitlines() if LOG_FILE.exists() else []
        lines = (lines + [json.dumps(row, ensure_ascii=False)])[-500:]
        LOG_FILE.write_text("\n".join(lines) + "\n", "utf-8")
    except Exception:  # noqa: BLE001
        pass


def guess_mood(text):
    for pattern, expr in MOOD_TABLE:
        if re.search(pattern, text):
            return expr
    moods, weights = FALLBACK_MOODS
    return random.choices(moods, weights=weights, k=1)[0]


def render_card(cfg, text, role, expr):
    """调渲染器画一张。返回 (路径, 错误)。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / ("card_%d_%03d.png" % (int(time.time()), random.randint(0, 999)))

    renderer = Path(cfg["renderer"])
    if not renderer.is_absolute():
        renderer = REPO_ROOT / renderer

    payload = {"role": role, "expr": expr, "text": text, "out": str(out)}
    project_dir = (cfg.get("project_dir") or "").strip()
    if project_dir:
        payload["project"] = project_dir
    else:
        cards = Path(cfg.get("cards") or "renderer/cards.json")
        payload["cards"] = str(cards if cards.is_absolute() else REPO_ROOT / cards)

    try:
        proc = subprocess.run(
            [cfg.get("python") or sys.executable, "-X", "utf8", str(renderer)],
            input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            capture_output=True,
            timeout=60,
        )
        raw = (proc.stdout or b"").decode("utf-8", "replace").strip().splitlines()
        data = json.loads(raw[-1]) if raw else {"ok": False, "error": "渲染器没有输出"}
        if not data.get("ok"):
            err = data.get("error", "渲染失败")
            tail = (proc.stderr or b"").decode("utf-8", "replace").strip().splitlines()[-3:]
            return None, (err + " | " + " / ".join(tail)) if tail else err
        return data.get("path"), None
    except Exception as exc:  # noqa: BLE001
        return None, repr(exc)


CREDIT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".credit.json")


def load_credit():
    """进位余量（0~1），跨消息保留，保证长期发图比例精确。"""
    try:
        with open(CREDIT_FILE, "r", encoding="utf-8") as f:
            v = float(json.load(f).get("credit", 0.0))
        if 0.0 <= v < 1.0:
            return v
    except Exception:
        pass
    return random.random()  # 首次随机起步，别永远卡在同一个相位


def save_credit(v):
    try:
        with open(CREDIT_FILE, "w", encoding="utf-8") as f:
            json.dump({"credit": round(float(v), 6)}, f)
    except Exception:
        pass


def roll_rate(rate):
    """按百分比决定这一句发不发，返回 (是否发, 新的进位)。

    做法是 Bresenham 式进位：每句把 rate/100 加进账本，攒够 1 就发一张、账本减 1。
    rate=30 时发送位置是第 4、7、10… 句，长期精确 30%，间隔稳定在 3~4 句。
    """
    credit = load_credit() + max(0.0, min(100.0, rate)) / 100.0
    hit = credit >= 1.0
    if hit:
        credit -= 1.0
    save_credit(credit)
    return hit, credit

def should_skip(chain, text, max_chars):
    """这条消息不该变成传话纸吗？返回 (跳过, 原因)。"""
    # Record 是 AstrBot 的语音组件：整句被转成语音时也要能画成牌子，所以不算「不适合」
    others = [type(c).__name__ for c in chain if type(c).__name__ not in ("Plain", "Record")]
    if others:
        return True, "has:" + ",".join(sorted(set(others))[:3])

    compact = "".join(text.split())
    if not compact:
        return True, "empty"
    if len(compact) > max_chars:
        return True, "too-long:%d" % len(compact)
    if URL_RE.search(text):
        return True, "url"

    cjk = sum(1 for ch in compact if "\u4e00" <= ch <= "\u9fff")
    if cjk == 0 or cjk / len(compact) < 0.4:
        return True, "lang:cjk=%d/%d" % (cjk, len(compact))

    return False, ""


class WhaleCardQQ(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    @filter.on_decorating_result()
    async def on_decorating(self, event: AstrMessageEvent):
        cfg = load_config()
        if not cfg.get("enabled", True):
            return

        result = event.get_result()
        chain = getattr(result, "chain", None) or []
        text = "".join(c.text for c in chain if isinstance(c, Plain)).strip()
        if not text:
            return

        skip, why = should_skip(chain, text, int(cfg.get("max_chars") or 28))
        if skip:
            append_log({"kind": "skip", "why": why, "text": text[:60]})
            return

        rate = max(0, min(100, int(cfg.get("rate") or 0)))
        if rate <= 0:
            append_log({"kind": "skip", "why": "rate 0%", "text": text[:60]})
            return
        # 「精准」发图：进位记账代替掷骰子 —— 每句加 rate/100，攒满 1 发一张。
        hit, credit = roll_rate(rate)
        if not hit:
            append_log({"kind": "skip", "why": "rate %d%% (credit %.2f)" % (rate, credit), "text": text[:60]})
            return

        expr = (guess_mood(text) if cfg.get("auto_mood", True) else None) or "#普通#"
        role = cfg.get("role") or "鲸鲸"

        path, err = await asyncio.to_thread(render_card, cfg, text, role, expr)
        if not path:
            append_log({"kind": "error", "text": text[:60], "role": role, "error": err})
            logger.warning("[whale-card] 渲染失败：%s", err)
            return

        if (cfg.get("mode") or "image") == "image":
            result.chain[:] = [c for c in chain if not isinstance(c, Plain)]
        result.chain.append(Image.fromFileSystem(path))

        append_log({
            "kind": "send",
            "text": text[:60],
            "role": role,
            "mood": expr.replace("#", ""),
            "target": "QQ 群聊（AstrBot）",
        })
        logger.info("[whale-card] 已把这句话画成传话纸发出：%s", path)
