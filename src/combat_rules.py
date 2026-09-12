"""战斗规则的运行时配置（`data/combat/rules/*.json`，缺失时用内置默认值）。

- `growth.json` —— 升级成长：每级属性点、是否自动分配到最低属性、属性上限
- `difficulty.json` —— 阶段带（T0–T4）缩放与威胁换算参数

配置只在启动时/首次读取时解析，文件变更按 mtime 自动失效（设计者改完即可生效，
不必重启，但也不为每次战斗重复读盘）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 放在 data/combat/rules/（引擎数据），不是 data/rules/（叙事规则文档目录，会被 wiki 检索）
RULES_DIR = _PROJECT_ROOT / "data" / "combat" / "rules"

DEFAULT_GROWTH: dict = {
    "attribute_points_per_level": 1,
    "auto_allocate_attribute_points": True,
    "attr_cap": 10,
    "specialization_points_per_level": 1,
    "node_unlock_every": 3,
}

DEFAULT_DIFFICULTY: dict = {
    # 阶段带：敌人数值倍率（apply_band_scaling 打开时生效）与威胁预算参考区间
    "bands": {
        "T0": {"enemy_hp_mult": 0.8, "enemy_atk_mult": 0.8, "threat_range": [1.0, 3.0]},
        "T1": {"enemy_hp_mult": 1.0, "enemy_atk_mult": 1.0, "threat_range": [3.0, 6.0]},
        "T2": {"enemy_hp_mult": 1.2, "enemy_atk_mult": 1.15, "threat_range": [6.0, 10.0]},
        "T3": {"enemy_hp_mult": 1.45, "enemy_atk_mult": 1.3, "threat_range": [10.0, 16.0]},
        "T4": {"enemy_hp_mult": 1.75, "enemy_atk_mult": 1.5, "threat_range": [16.0, 30.0]},
    },
    # 节点未显式开启时不做阶段带缩放（保持"敌人数值即文件终值"的直觉）
    "default_apply_band_scaling": False,
    # 实际威胁与声明预算的偏差容差（校验器据此给警告）
    "threat_tolerance": 0.25,
}

_cache: dict[str, tuple[float, dict]] = {}


def _load(name: str, defaults: dict) -> dict:
    path = RULES_DIR / f"{name}.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return dict(defaults)

    cached = _cache.get(name)
    if cached and cached[0] == mtime:
        return cached[1]

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("配置应为 JSON 对象")
    except (OSError, ValueError) as exc:
        logger.warning("战斗规则 %s 解析失败，使用默认值: %s", path.name, exc)
        return dict(defaults)

    merged = {**defaults, **data}
    _cache[name] = (mtime, merged)
    return merged


def growth_rules() -> dict:
    """升级成长规则（`data/rules/growth.json`）。"""
    return _load("growth", DEFAULT_GROWTH)


def difficulty_rules() -> dict:
    """阶段带与威胁规则（`data/rules/difficulty.json`）。"""
    return _load("difficulty", DEFAULT_DIFFICULTY)


def band_config(band: str) -> dict:
    """取某阶段带的配置（未知阶段带回落 T1）。"""
    bands = difficulty_rules().get("bands") or {}
    return bands.get(str(band or "").upper()) or bands.get("T1") or {}


def band_scaling(band: str) -> tuple[float, float]:
    """阶段带的敌人数值倍率 (hp_mult, atk_mult)。"""
    cfg = band_config(band)
    try:
        hp = float(cfg.get("enemy_hp_mult", 1.0) or 1.0)
        atk = float(cfg.get("enemy_atk_mult", 1.0) or 1.0)
    except (TypeError, ValueError):
        return 1.0, 1.0
    return max(0.1, hp), max(0.1, atk)
