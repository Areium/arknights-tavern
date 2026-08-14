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
name: "默认战场"
summary: "通用战斗背景：阴云密布的荒原，适配大多数野外遭遇战。"
type: combat_background
image: "bg.jpg"
prompt: "Arknights style anime background art, desolate wilderness battlefield under overcast sky, cracked dry earth, scattered rocks and industrial debris in the distance, slightly elevated camera angle looking down at an open empty ground plane in the center, muted cold grey-blue palette with a faint amber horizon glow, dark atmospheric lighting, heavy vignette, no characters, no text, no UI, painterly matte painting quality, 16:9"
negative_prompt: "people, characters, text, watermark, logo, UI elements, bright sunny colors, close-up, first-person view"
source: placeholder
size: "1920x1080"
---

# 默认战场

所有未指定背景的场所的回退选项。构图要求：画面中央偏下留出开阔空地
（供 7×7 网格悬浮），远景放置地标元素，整体偏暗以匹配深色 UI。
