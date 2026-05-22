import json
import os
import re
import logging

import frontmatter

logger = logging.getLogger(__name__)


class SceneObject:
    """场景中的单个物体。"""

    def __init__(
        self,
        name: str,
        description: str = "",
        state: dict = None,
        portable: bool = True,
        visible: bool = True,
        container: str = "",
    ):
        self.name = name
        self.description = description
        self.state = state or {}
        self.portable = portable
        self.visible = visible
        self.container = container

    def to_context(self) -> str:
        """格式化为一行上下文文本。"""
        parts = [self.name]
        if self.state:
            state_str = ", ".join(f"{k}:{v}" for k, v in self.state.items())
            parts.append(f"({' '.join(state_str)})")
        if self.description:
            parts.append(f"— {self.description[:60]}")
        if self.container:
            parts.append(f"[在{self.container}中]")
        return " ".join(parts)


class EnvironmentState:
    """环境状态管理器：位置、天气、时段、氛围、场景物品。"""

    def __init__(self, data_dir: str = "environment"):
        self.data_dir = data_dir
        self.location = ""
        self.location_desc = ""
        self.weather = ""
        self.weather_desc = ""
        self.time_of_day = "上午"
        self.atmosphere: list[str] = []
        self.scene_objects: dict[str, SceneObject] = {}

    # ── 文件加载 ──

    def load_default(self):
        """加载默认场景：第一个可用地点 + 晴天。"""
        locations = self._list_locations()
        if locations:
            self.load_location(locations[0])
        else:
            self.location = "罗德岛"
            self.location_desc = "罗德岛舰船内部"
        self.load_weather("sunny")

    def load_location(self, name: str) -> bool:
        """从 environment/Location/ 下加载地点描述及默认物品。

        name 可以是文件名（含别名）或 frontmatter 中的 name 字段。
        """
        base = os.path.join(self.data_dir, "Location")
        if not os.path.isdir(base):
            return False

        # 第一遍：按文件名匹配（精确 + 别名）
        for root, _dirs, files in os.walk(base):
            for f in files:
                stem = os.path.splitext(f)[0]
                if stem == name:
                    return self._parse_location_file(os.path.join(root, f))
                # 别名匹配：Training Room ↔ 训练室
                try:
                    with open(os.path.join(root, f), "r", encoding="utf-8") as fh:
                        meta = frontmatter.load(fh).metadata
                    if meta.get("alias") == name or meta.get("name") == name:
                        return self._parse_location_file(os.path.join(root, f))
                except Exception:
                    continue

        logger.info("未找到地点文件: %s", name)
        return False

    def load_weather(self, name: str) -> bool:
        """从 environment/weather/ 加载天气描述。

        name 可以是文件名(如 sunny)或 frontmatter name(如 晴天)。
        """
        # 精确文件名匹配
        filepath = os.path.join(self.data_dir, "weather", f"{name}.md")
        if os.path.isfile(filepath):
            return self._parse_weather_file(filepath)

        # 扫描 frontmatter name/别名匹配
        base = os.path.join(self.data_dir, "weather")
        if os.path.isdir(base):
            for f in os.listdir(base):
                if not f.endswith(".md"):
                    continue
                try:
                    with open(os.path.join(base, f), "r", encoding="utf-8") as fh:
                        meta = frontmatter.load(fh).metadata
                    wtype = meta.get("weather_type", {})
                    if wtype.get("name") == name or wtype.get("id") == name:
                        return self._parse_weather_file(os.path.join(base, f))
                except Exception:
                    continue

        logger.info("未找到天气文件: %s", name)
        return False

    # ── 上下文构建（注入 prompt）──

    def build_context(self) -> str:
        """构建可用于注入角色 prompt 的【当前场景】上下文。"""
        parts = ["【当前场景】"]
        if self.location:
            desc_short = ""
            if self.location_desc:
                # 取描述的第一段（概要）
                m = re.search(r"# .*?\n\n(.+?)(?:\n\n|$)", self.location_desc)
                if m:
                    desc_short = m.group(1).strip()[:120]
            parts.append(f"位置: {self.location}")
            if desc_short:
                parts.append(f"  {desc_short}")

        if self.weather:
            parts.append(f"天气: {self.weather}")

        if self.time_of_day:
            parts.append(f"时间: {self.time_of_day}")

        if self.atmosphere:
            parts.append(f"氛围: {'、'.join(self.atmosphere)}")

        visible = [o for o in self.scene_objects.values() if o.visible]
        if visible:
            parts.append("\n【场景物品】")
            for obj in visible:
                parts.append(f"- {obj.to_context()}")

        return "\n".join(parts)

    # ── 状态更新 ──

    def apply_update(self, updates: dict):
        """应用 LLM 通过 <!--env:...--> 标记传递的环境更新。"""
        if not updates:
            return

        loc = updates.get("location")
        if loc and loc != self.location:
            # 先尝试从文件加载新地点的详情
            if not self.load_location(loc):
                # 找不到文件则按普通名字记录
                self.location = loc
                self.location_desc = ""

        weather = updates.get("weather")
        if weather and weather != self.weather:
            if not self.load_weather(weather):
                self.weather = weather

        time_ = updates.get("time")
        if time_:
            self.time_of_day = time_

        objs = updates.get("objects")
        if objs:
            self._apply_object_updates(objs)

    def set_location(self, name: str):
        """强制切换到指定地点。"""
        if not self.load_location(name):
            self.location = name
            self.location_desc = ""
        # 切换地点时清除旧地点的不可移动物品
        self.scene_objects = {
            k: v for k, v in self.scene_objects.items()
            if v.portable
        }

    def set_weather(self, name: str):
        """强制切换天气。"""
        if not self.load_weather(name):
            self.weather = name
            self.weather_desc = ""

    def add_object(self, name: str, **kwargs):
        """添加或更新场景物品。"""
        if name in self.scene_objects:
            obj = self.scene_objects[name]
            for key, val in kwargs.items():
                if key == "state" and isinstance(val, dict):
                    obj.state.update(val)
                elif key == "visible":
                    obj.visible = val
                elif hasattr(obj, key):
                    setattr(obj, key, val)
            obj.visible = True
        else:
            self.scene_objects[name] = SceneObject(name=name, **kwargs)

    def remove_object(self, name: str):
        """将物品标记为不可见（逻辑删除）。"""
        if name in self.scene_objects:
            self.scene_objects[name].visible = False

    def reset(self):
        """清空全部环境状态。"""
        self.location = ""
        self.location_desc = ""
        self.weather = ""
        self.weather_desc = ""
        self.time_of_day = "上午"
        self.atmosphere = []
        self.scene_objects.clear()

    # ── 内部方法 ──

    def _parse_location_file(self, filepath: str) -> bool:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = frontmatter.load(f)
            meta = data.metadata
            content = data.content

            self.location = meta.get("name", os.path.splitext(os.path.basename(filepath))[0])
            self.location_desc = content

            # 加载新地点时清空旧场景物品（被携带的物品由 LLM 通过 env 标记恢复）
            self.scene_objects.clear()

            # 从 "### 细节" 段落提取默认物品
            detail_lines = []
            in_details = False
            for line in content.split("\n"):
                stripped = line.strip()
                if stripped.startswith("### 细节"):
                    in_details = True
                    continue
                if in_details:
                    if stripped.startswith("## ") or stripped.startswith("### "):
                        break
                    if stripped.startswith("- ") or stripped.startswith("* "):
                        detail_lines.append(stripped[2:])

            self._parse_detail_objects(detail_lines)
            return True
        except Exception as e:
            logger.error("解析地点文件失败 %s: %s", filepath, e)
            return False

    def _parse_weather_file(self, filepath: str) -> bool:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = frontmatter.load(f)
            meta = data.metadata
            content = data.content
            wtype = meta.get("weather_type", {})
            self.weather = wtype.get("name", os.path.splitext(os.path.basename(filepath))[0])
            self.weather_desc = content
            return True
        except Exception as e:
            logger.error("解析天气文件失败 %s: %s", filepath, e)
            return False

    def _parse_detail_objects(self, lines: list[str]):
        """从地点文件的细节段落提取默认物品。"""
        for line in lines:
            line = line.strip()
            if not line:
                continue

            obj_name = None

            # 1) 优先提取粗体名称 **Name**
            bold = re.match(r"\*\*(.+?)\*\*[：:]?\s*(.*)", line)
            if bold:
                self._add_detail_object(
                    name=bold.group(1).strip(),
                    desc=bold.group(2).strip() or line,
                    line=line,
                )
                continue

            # 2) 按 "的" 切分，取最后一段作为物品名
            parts = line.split("的")
            if len(parts) >= 2:
                # 去掉尾部标点和子句
                raw = parts[-1].strip()
                clean = re.split(r"[，。；,;]", raw, maxsplit=1)[0].strip()
                name = clean if clean and len(clean) >= 2 else raw

                # 如果最后一段是抽象概念而非具体物品，尝试往前找
                abstract_words = {
                    "流逝", "痕迹", "感觉", "氛围", "气息", "样子", "存在",
                    "过程", "结果", "活动", "状态", "方式", "时刻", "瞬间",
                    "色彩", "亮度", "训练", "动作", "性能", "数据",
                    "记录", "信息", "情况", "程度", "水平",
                }
                if name in abstract_words and len(parts) >= 3:
                    # 取倒数第二段
                    raw2 = parts[-2].strip()
                    clean2 = re.split(r"[，。；,;]", raw2, maxsplit=1)[0].strip()
                    if clean2 and len(clean2) >= 2:
                        name = clean2
                    else:
                        name = raw2 if len(raw2) >= 2 else name

                self._add_detail_object(name=name, desc=line, line=line)
                continue

            # 3) 无 "的" 的情况：尝试提取句子中的具体名词
            #    去掉冠词量词后，找 "着" 后面的名词，或取第一个有意义的词语
            cleaned = re.sub(
                r"^(一张|一个|一件|一处|一间|某个|几个|各种|许多|一些|一面|一条|一扇|一台|一座)",
                "",
                line,
                count=1,
            )
            # 优先找 "着" 后面的名词
            after_zhe = re.search(r"着(.{2,8})(?:[，。；]|$)", cleaned)
            if after_zhe:
                name = after_zhe.group(1).strip()
            else:
                # 取第一个名词性短语
                m = re.match(r"[一-鿿]{2,8}", cleaned)
                if m:
                    name = m.group(0)
                else:
                    continue
            self._add_detail_object(name=name, desc=line, line=line)

    def _add_detail_object(self, name: str, desc: str, line: str):
        """添加从细节中提取的物品（带长度/抽象性/便携性检查）。"""
        if name in self.scene_objects:
            return
        # 跳过过长或过短的名字
        if len(name) > 8 or len(name) < 2:
            return
        # 跳过抽象概念
        abstract_words = {
            "流逝", "痕迹", "感觉", "氛围", "气息", "样子", "存在",
            "过程", "结果", "活动", "状态", "方式", "时刻", "瞬间",
            "色彩", "亮度", "训练", "动作", "性能", "数据",
            "记录", "信息", "情况", "程度", "水平",
        }
        if any(ab in name for ab in abstract_words):
            return
        portable = not any(
            kw in line for kw in ["固定", "嵌入式", "墙壁", "墙上", "挂着", "悬挂"]
        )
        self.scene_objects[name] = SceneObject(
            name=name, description=desc, portable=portable
        )

    def _list_locations(self) -> list[str]:
        """递归扫描 environmnt/Location/ 下的地点文件。"""
        base = os.path.join(self.data_dir, "Location")
        if not os.path.isdir(base):
            return []
        locs = []
        for root, _dirs, files in os.walk(base):
            for f in files:
                if f.endswith(".md"):
                    locs.append(os.path.splitext(f)[0])
        return locs

    def _apply_object_updates(self, objects: dict):
        """应用物体更新。"""
        for obj_name, obj_data in objects.items():
            action = obj_data.get("action", "update")
            if action == "remove":
                self.remove_object(obj_name)
            elif action == "add":
                kwargs = {k: v for k, v in obj_data.items() if k != "action"}
                self.add_object(obj_name, **kwargs)
            else:  # update / move
                kwargs = {k: v for k, v in obj_data.items() if k != "action"}
                self.add_object(obj_name, **kwargs)
