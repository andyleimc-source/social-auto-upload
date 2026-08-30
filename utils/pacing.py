"""发布节奏控制：把「每一步之间停多久」「打字多快」做成可调参数。

为什么要有这个：默认代码是机器速度——填完标题下一毫秒就填正文，整条发布 20 秒跑完，
这在平台风控眼里跟真人差得非常远。小红书尤其严。这里给每个步骤一个随机区间的停顿，
并让文字逐字输入，整体拉到真人量级。

调整方式（不用改代码）：
  1. 改 `pacing.json`（放在 social-auto-upload 根目录，格式同下面的 DEFAULTS，只写要改的键）
  2. 环境变量 `SAU_PACING_SCALE=1.5` 全局放慢 1.5 倍（0.5 = 加快一倍）
  3. 环境变量 `SAU_PACING_OFF=1` 完全关掉停顿（只该在调试选择器时用，别拿去发正式内容）

每个区间是 [下限秒, 上限秒]，实际取区间内随机值——固定值本身就是一种机器特征。
"""
from __future__ import annotations

import asyncio
import json
import os
import random
from pathlib import Path

from conf import BASE_DIR

# 步骤名 -> [最短秒, 最长秒]
DEFAULTS: dict[str, dict[str, list]] = {
    "_default": {
        "page_ready": [2.0, 4.0],        # 打开发布页、页面稳定后
        "before_upload": [1.5, 3.0],     # 选视频文件前
        "after_upload": [3.0, 6.0],      # 视频传完、开始填表前
        "before_title": [1.5, 3.5],      # 点进标题框前
        "before_desc": [1.5, 3.0],       # 从标题移到正文
        "before_tags": [1.0, 2.5],       # 正文写完、开始打标签
        "between_tags": [0.6, 1.6],      # 每个标签之间
        "before_cover": [2.5, 5.0],      # 去设封面
        "in_cover_dialog": [1.5, 3.0],   # 封面弹窗里每一下
        "before_schedule": [2.0, 4.0],   # 去设定时
        "before_submit": [3.0, 6.0],     # 点发布前最后一停（人会再看一眼）
        "type_delay_ms": [55, 145],      # 逐字输入，每个字符的间隔
    },
    # 小红书风控最严，整体再放慢一档
    "xiaohongshu": {
        "page_ready": [3.0, 6.0],
        "before_upload": [2.0, 4.0],
        "after_upload": [4.0, 8.0],
        "before_title": [2.5, 5.0],
        "before_desc": [2.0, 4.5],
        "before_tags": [1.5, 3.5],
        "between_tags": [0.9, 2.2],
        "before_cover": [3.5, 7.0],
        "in_cover_dialog": [2.0, 4.5],
        "before_schedule": [2.5, 5.0],
        "before_submit": [4.0, 8.0],
        "type_delay_ms": [75, 190],
    },
}

_CONFIG_PATH = Path(BASE_DIR) / "pacing.json"


def _load() -> dict:
    cfg = {k: dict(v) for k, v in DEFAULTS.items()}
    try:
        if _CONFIG_PATH.exists():
            for platform, steps in json.loads(_CONFIG_PATH.read_text()).items():
                cfg.setdefault(platform, {}).update(steps)
    except Exception:
        pass  # 配置写坏了就用默认值，不要因为节奏配置把发布搞挂
    return cfg


def _scale() -> float:
    try:
        return max(0.0, float(os.environ.get("SAU_PACING_SCALE", "1")))
    except ValueError:
        return 1.0


def _disabled() -> bool:
    return os.environ.get("SAU_PACING_OFF") == "1"


def _range(step: str, platform: str) -> list:
    cfg = _load()
    return cfg.get(platform, {}).get(step) or cfg["_default"].get(step) or [0, 0]


async def pause(step: str, platform: str = "_default") -> None:
    """在某个步骤前后停一下，时长是配置区间内的随机值。"""
    if _disabled():
        return
    lo, hi = _range(step, platform)[:2]
    await asyncio.sleep(random.uniform(lo, hi) * _scale())


def type_delay(platform: str = "_default") -> float:
    """逐字输入时每个字符的间隔（毫秒），给 Playwright 的 type(delay=...) 用。"""
    if _disabled():
        return 0
    lo, hi = _range("type_delay_ms", platform)[:2]
    return random.uniform(lo, hi) * _scale()


async def human_type(page, text: str, platform: str = "_default") -> None:
    """逐字输入。长文本按标点断句，句子之间多停一下——真人不会一口气匀速打完 200 字。"""
    if _disabled() or not text:
        await page.keyboard.type(text)
        return
    chunk = ""
    for ch in text:
        chunk += ch
        if ch in "。！？\n" and len(chunk) >= 8:
            await page.keyboard.type(chunk, delay=type_delay(platform))
            await asyncio.sleep(random.uniform(0.3, 1.1) * _scale())
            chunk = ""
    if chunk:
        await page.keyboard.type(chunk, delay=type_delay(platform))
