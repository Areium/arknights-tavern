import sys
import time

import readchar
from readchar import key as kbd


_TOGGLE_MODE = "__TOGGLE_MODE__"
_CONTINUE = "__CONTINUE__"


class OptionsMenu:
    """键盘可导航的对话选项选择器。

    用法:
        menu = OptionsMenu(options, mode="system", character_name="霜星")
        selected = menu.run()  # 返回选中文本或 _TOGGLE_MODE

    模式:
        系统模式 — 系统操作选项（角色管理、环境设置等）
        角色模式 — 角色对话选项（与当前角色交互）
        Tab 键在两种模式间切换。
    """

    TOGGLE = _TOGGLE_MODE
    CONTINUE = _CONTINUE

    def __init__(self, options: list[str], mode: str = "system",
                 character_name: str = "", scene_characters: list[str] | None = None):
        self.options = list(options)
        # 内部追加「自行输入」作为最后一个可选项
        self._items = list(options) + ["自行输入..."]
        self.mode = mode
        self.character_name = character_name
        self.scene_characters = scene_characters or []
        self.selected = 0

    def run(self) -> str | None:
        """显示菜单并返回用户选择的文本、TOGGLE 或 None（退出）。"""
        self._render()

        while True:
            key = readchar.readkey()

            if key == kbd.UP:
                self.selected = (self.selected - 1) % len(self._items)
                self._render()
            elif key == kbd.DOWN:
                self.selected = (self.selected + 1) % len(self._items)
                self._render()
            elif key == kbd.TAB:
                return self.TOGGLE
            elif key == kbd.ENTER:
                return self._resolve_selection()
            elif key in ("1", "2", "3", "4"):
                idx = int(key) - 1
                if idx < len(self._items):
                    self.selected = idx
                    return self._resolve_selection()
            elif key.lower() == "q":
                print()
                return None

    # ── 内部方法 ──

    def _resolve_selection(self) -> str:
        """处理当前选中项：正常选项返回文本，「自行输入」进入输入模式。"""
        print()
        if self.selected < len(self.options):
            return self.options[self.selected]
        else:
            return self._custom_input()

    def _render(self):
        """渲染选项列表，高亮当前选中项。"""
        if hasattr(self, "_line_count"):
            for _ in range(self._line_count):
                sys.stdout.write("\033[A\033[K")
            sys.stdout.flush()

        if self.mode == "system":
            header = "【系统模式】"
        else:
            if self.scene_characters:
                chars = " · ".join(self.scene_characters)
            else:
                chars = self.character_name
            header = f"【剧情模式】{chars}"

        lines = [
            f"{header}  (Tab 切换, ↑↓ 选择, Enter 确认)",
            "",
        ]
        for i, opt in enumerate(self._items):
            if i == self.selected:
                lines.append(f"  \033[7m[{i + 1}] {opt}\033[0m")
            else:
                lines.append(f"  [{i + 1}] {opt}")
        lines.append("  [q] 退出程序")

        output = "\n".join(lines)
        self._line_count = len(lines)
        print(output, flush=True)

    @staticmethod
    def _custom_input() -> str:
        return input("请输入: ")


def stream_print(text: str, delay: float = 0.03):
    """逐字符流式输出文本（打字机效果），末尾自动换行。"""
    for ch in text:
        print(ch, end="", flush=True)
        time.sleep(delay)
    print()
