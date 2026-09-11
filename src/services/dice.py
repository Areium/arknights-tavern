"""
d20 骰子系统。

支持：
  - d20 基础掷骰 + 修正值 + DC 判定
  - 自然 20/1 的大成功/大失败
"""

import random
import logging

logger = logging.getLogger(__name__)


class DiceSystem:
    """d20 掷骰系统。"""

    @staticmethod
    def roll_d20_structured(
        modifier: int = 0, difficulty: int | None = None
    ) -> dict:
        """掷 20 面骰子，返回结构化结果字典。

        Returns:
            {"roll": int, "modifier": int, "total": int,
             "difficulty": int|None, "success": bool|None, "text": str}
        """
        roll = random.randint(1, 20)
        total = roll + modifier

        success = None
        if difficulty is not None:
            if roll == 20:
                success = True      # 自然 20 = 大成功（必成）
            elif roll == 1:
                success = False     # 自然 1 = 大失败（必败）
            else:
                success = total >= difficulty

        text = DiceSystem._format_roll(roll, modifier, total, difficulty, success)

        return {
            "roll": roll,
            "modifier": modifier,
            "total": total,
            "difficulty": difficulty,
            "success": success,
            "text": text,
        }

    @staticmethod
    def roll_d20(modifier: int = 0, difficulty: int | None = None) -> str:
        """掷 20 面骰子，返回格式化的结果字符串。"""
        return DiceSystem.roll_d20_structured(modifier, difficulty)["text"]

    @staticmethod
    def _format_roll(
        roll: int,
        modifier: int,
        total: int,
        difficulty: int | None,
        success: bool | None,
    ) -> str:
        """格式化掷骰结果为可读字符串。"""
        parts = [f"🎲 掷出 d20: **{roll}**"]
        if modifier != 0:
            sign = "+" if modifier > 0 else ""
            parts.append(f" (修正 {sign}{modifier})")
        if modifier != 0:
            parts.append(f" = **{total}**")

        if difficulty is not None:
            if success:
                parts.append(f"  ✅ 成功 (DC {difficulty})")
            else:
                parts.append(f"  ❌ 失败 (DC {difficulty})")
        if roll == 20:
            parts.append("  🌟 大成功！")
        elif roll == 1:
            parts.append("  💀 大失败！")

        return "".join(parts)
