---
# ==============================================================================
# 战斗背景条目 (Combat Background)
# ==============================================================================
# 每个背景是一个实体目录：data/combat/backgrounds/<bg_id>/
#   index.md  — 本文件，存放元信息与 AI 生成提示词
#   <image>   — 背景图片文件（png/jpg/webp），frontmatter image 字段指定；
#               未指定时自动取目录下第一个图片文件
#
# ── Frontmatter 字段说明 ──
# name:           背景中文名（必填），用于文档管理界面展示
# summary:        一句话摘要（≤50 字）
# type:           固定为 "combat_background"
# image:          图片文件名（生成/放入图片后填写；留空且目录无图时回退纯色背景）
# prompt:         文生图提示词（英文，供 tools/generate_combat_backgrounds.py 使用）
# negative_prompt: 负面提示词（可选）
# source:         ai / manual（图片来源）
# size:           建议尺寸（默认 1920x1080）
# ─────────────────────────────────────────────────────────────────────────────
# 选用优先级：遭遇战 frontmatter 的 background 字段 → 地点 frontmatter 的
# combat_bg 字段 → 本 default 背景。提示词写法见 docs/combat-background-prompts.md
# ==============================================================================
name: "雪山战场"
summary: "谢拉格雪山战场：暴风雪中的冰原与圣山，适配雪境遭遇战。"
type: combat_background
image: "bg.jpg"
prompt: "Arknights style anime background art, snow-covered Kjerag mountain battlefield, blizzard under a heavy grey sky, towering icy cliffs and snow-dusted pine trees in the distance, a wide frozen snowfield ground plane in the center with wind-blown snow drifts, faint glacial peaks rising behind, cold blue-white palette with pale cyan highlights, dim overcast lighting, soft falling snowflakes, heavy atmospheric haze, no characters, no text, no UI, painterly matte painting quality, 16:9"
negative_prompt: "people, characters, text, watermark, logo, UI elements, warm bright colors, sunshine, clear blue sky, close-up, first-person view"
source: placeholder
size: "1920x1080"
---

# 雪山战场

谢拉格圣山区域遭遇战的专用背景。构图要求：画面中央偏下留出开阔的
积雪空地（供 7×7 网格悬浮），远景放置冰崖与雪松作为地标，整体以
冷蓝白配色 + 暴风雪氛围匹配谢拉格雪境的叙事基调。图片暂缺时前端
回退纯色背景，不影响战斗流程，后续可用 tools/generate_combat_backgrounds.py
按 prompt 生成后填入 image 字段。
