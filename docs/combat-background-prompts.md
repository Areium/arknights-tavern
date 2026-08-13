# 战斗背景场景提示词方案

为战斗界面设计 AI 文生图背景的统一规范。目标是：任何人生成（作者提前批量生成，或玩家自行生成）出来的图，放进战斗界面都"能用、好看、风格不打架"。

## 1. 界面约束（构图要求的来源）

战斗界面的布局决定了背景图必须满足特定构图，否则再好的图也会被 UI 切碎：

| 界面元素 | 位置 | 对背景的要求 |
|---|---|---|
| 7×7 网格（rotateX 33° 俯视倾斜） | 画面中央 | 中央偏下必须是**开阔、低细节的地面**，否则格子看不清 |
| 左右角色状态面板 | 两侧（各约 224px） | 两侧内容会被遮挡，重要元素勿放两侧 |
| 手牌区 + 操作栏 | 底部（约 200px） | 底部三分之一应偏暗、低对比 |
| 回合计数文字 | 顶部中央 | 顶部应有暗色区域或可被渐变压暗 |
| 前端压暗渐变遮罩 | 全屏 | 图可以比预期稍亮，遮罩会统一压暗 30%-70% |

由此得出硬性构图规范（写进每一条提示词）：

1. **轻微俯视视角**（slightly elevated camera angle）——与网格的 33° 倾斜方向一致，让格子读起来像"躺在地面上"
2. **中央开阔地面**（an open empty ground plane in the center）——地面材质可有质感（龟裂土地、钢板、积雪），但不能有遮挡物、强光斑
3. **地标放远景**（…in the distance）——城市轮廓、机械、废墟等叙事元素全部放地平线附近
4. **无人物、无文字、无 UI**（no characters, no text, no UI）
5. **整体偏暗 + 重暗角**（dark atmospheric lighting, heavy vignette）——匹配深色 UI 主题
6. **16:9**，建议 1920×1080 起步

## 2. 基础提示词模板

英文提示词效果普遍好于中文，统一用英文写。模板：

```
Arknights style anime background art,
{scene},                       ← 场景主体（1-2 句，见第 3 节配方）
{landmark} in the distance,    ← 远景地标（点明地点身份）
{weather_or_atmosphere},       ← 天气/氛围（可选）
slightly elevated camera angle looking down at an open empty {ground} ground plane in the center,
{ground} 如 cracked dry earth / steel deck / snow-covered street
muted {palette} palette with {accent} accent,
dark atmospheric lighting, heavy vignette,
no characters, no text, no UI,
painterly matte painting quality, 16:9
```

负面提示词（通用，直接复用）：

```
people, characters, text, watermark, logo, UI elements, bright sunny colors, close-up, first-person view
```

## 3. 风格一致性控制

所有背景共用同一组"风格锚点"（模板的首尾句）：

- 开头 `Arknights style anime background art` —— 锚定明日方舟式冷峻工业幻想画风
- 结尾 `painterly matte painting quality` —— 锚定厚涂/哑光质感，避免照片感或二次元平涂跑偏
- 配色遵守「低饱和底色 + 单一强调色」原则，常用配色槽：

| 场景类型 | palette（底色） | accent（强调色） |
|---|---|---|
| 荒野/废土 | cold grey-blue / ochre and slate grey | amber horizon / orange warning lights |
| 城市夜景 | deep blue-black | neon teal / warm window lights |
| 罗德岛舰内 | cool steel grey | faint blue hologram glow |
| 雪地/冰原 | pale desaturated blue-white | dim red emergency lights |
| 室内暖景 | warm brown-grey | soft amber lamp light |

## 4. 场景配方示例

可直接填入 `data/combat/backgrounds/<bg_id>/index.md` 的 `prompt` 字段。

**荒野（default，已内置）**
```
Arknights style anime background art, desolate wilderness battlefield under overcast sky, cracked dry earth, scattered rocks and industrial debris in the distance, slightly elevated camera angle looking down at an open empty ground plane in the center, muted cold grey-blue palette with a faint amber horizon glow, dark atmospheric lighting, heavy vignette, no characters, no text, no UI, painterly matte painting quality, 16:9
```

**矿区废墟（wasteland_ruins，已内置）**
```
Arknights style anime background art, abandoned mining ruins on the wasteland outside a nomadic city, collapsed concrete structures and rusted originium extraction machinery in the distance, dust haze, slightly elevated camera angle looking down at an open empty cracked-asphalt ground plane in the center, desaturated ochre and slate grey palette with dim orange warning lights, oppressive post-industrial atmosphere, heavy vignette, no characters, no text, no UI, painterly matte painting quality, 16:9
```

**龙门街区夜景**
```
Arknights style anime background art, rain-slicked downtown street of Lungmen at night, dense neon signs and towering skyscrapers in the distance, wet reflections, slightly elevated camera angle looking down at an open empty wet asphalt ground plane in the center, deep blue-black palette with neon teal and magenta accents, dark atmospheric lighting, heavy vignette, no characters, no text, no UI, painterly matte painting quality, 16:9
```

**罗德岛甲板**
```
Arknights style anime background art, open landing deck of the Rhodes Island landship, railings and signal lights at deck edges, vast overcast sky and distant moving city silhouettes in the distance, slightly elevated camera angle looking down at an open empty steel deck ground plane in the center, cool steel grey palette with faint blue hologram glow, dark atmospheric lighting, heavy vignette, no characters, no text, no UI, painterly matte painting quality, 16:9
```

**雪原**
```
Arknights style anime background art, frozen tundra of Ursus under a blizzard, broken watchtowers and pine forest silhouettes in the distance, wind-blown snow haze, slightly elevated camera angle looking down at an open empty snow-covered ground plane in the center, pale desaturated blue-white palette with dim red emergency lights, dark atmospheric lighting, heavy vignette, no characters, no text, no UI, painterly matte painting quality, 16:9
```

## 5. 各平台参数建议

| 平台 | 参数 |
|---|---|
| SD / SDXL / 本地模型 | 1920×1080（或 1344×768 后超分）；CFG 6-8；steps 28-40；把第 2 节负面提示词填入 negative |
| Midjourney | 末尾加 `--ar 16:9 --no people text watermark --style raw`；负面词用 `--no` 表达 |
| DALL·E 3 / gpt-image | size 选 1792×1024；不支持负面词，把 "no characters, no text" 留在正文即可 |
| 国产 OpenAI 兼容接口（豆包/通义万相/硅基流动等） | size 1920×1080 或最接近档位；正文直用模板 |

生成后挑出最符合构图规范的一张：先看中央地面是否干净，再看整体亮度，最后看风格。中央地面不合格的直接弃用，不要指望遮罩救回来。

## 6. 两条工作流

### 作者：写剧本时提前生成

1. 给地点文件（`data/environment/Location/**/index.md`）加 `combat_bg: <bg_id>`，或在遭遇战 frontmatter 加 `background: <bg_id>`
2. 运行 `python tools/generate_combat_backgrounds.py --scaffold`：为引用了但还不存在的背景自动建目录和 index.md，并按地点文档的「描述/视觉」段落拼好提示词草稿
3. 人工审一遍提示词草稿（重点改 `{scene}` 和配色槽）
4. 配置 `config/image_config.json` 后运行 `python tools/generate_combat_backgrounds.py` 批量出图，图片和 image 字段自动写入

### 玩家：自行生成

1. 在文档管理界面找到「战斗组件 → combat_backgrounds」，复制一个现有条目改 `prompt`
2. 用任意工具出图（按第 5 节参数），在文档管理的图片上传处把图传进该条目目录
3. 把 index.md 的 `image` 字段改为图片文件名——下一次进入相关战斗即生效

也可以运行 `python tools/generate_combat_backgrounds.py --dry-run`，把所有缺图背景的提示词打印出来，逐条粘贴到自己顺手的生图工具里。

### 单个会话：会话级覆盖（不调全局）

每个会话有独立背景目录（会话详情接口 `backgrounds_dir` 字段给出绝对路径）：

```
data/memory/sessions/<story|free>/<会话ID>/backgrounds/
```

直接把图片文件丢进去即可，按文件名生效：

- `<bg_id>.jpg`（如 `wasteland_ruins.jpg`）——替换该场战斗中对应 ID 的背景
- `default.jpg`——替换本会话的兜底背景

适合边玩边换：生成一张图 → 放进目录 → 下一场战斗自动用上，不影响其他会话和全局条目。完整选用优先级：**会话覆盖图 > 全局图**，同一背景 ID 内先查会话目录；背景 ID 本身仍按「遭遇战 `background` → 地点 `combat_bg` → default」确定。
