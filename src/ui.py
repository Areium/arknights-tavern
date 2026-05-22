import readchar
from readchar import key as kbd


class OptionsMenu:
    """键盘可导航的对话选项选择器。

    用法:
        menu = OptionsMenu(options)
        selected = menu.run()  # 返回选中文本
    """

    def __init__(self, options: list[str]):
        self.options = options
        self.selected = 0

    def run(self) -> str:
        """显示菜单并返回用户选择的文本。"""
        self._render()

        while True:
            key = readchar.readkey()

            if key == kbd.UP:
                self.selected = (self.selected - 1) % len(self.options)
                self._render()
            elif key == kbd.DOWN:
                self.selected = (self.selected + 1) % len(self.options)
                self._render()
            elif key == kbd.ENTER:
                print()
                return self.options[self.selected]
            elif key == kbd.TAB:
                return self._custom_input()
            elif key in ("1", "2", "3"):
                idx = int(key) - 1
                if idx < len(self.options):
                    print()
                    return self.options[idx]

    # ── 内部方法 ──

    def _render(self):
        """渲染选项列表，高亮当前选中项。"""
        if hasattr(self, "_line_count"):
            # 回移光标覆盖之前输出
            print(f"\033[{self._line_count}A", end="")

        lines = [
            "请选择对话选项 (↑↓ 切换, Enter 确认, Tab 自行输入, 1/2/3 快捷键):",
            "",
        ]
        for i, opt in enumerate(self.options):
            if i == self.selected:
                lines.append(f"  \033[7m[{i + 1}] {opt}\033[0m")
            else:
                lines.append(f"  [{i + 1}] {opt}")
        lines.extend(["", "  [*] 自行输入..."])

        output = "\n".join(lines)
        self._line_count = len(lines)
        print(output, end="\r\n")

    def _custom_input(self) -> str:
        """清除菜单并切换到自定义输入模式。"""
        print(f"\033[{self._line_count}A\033[J", end="")
        return input("请输入: ")
