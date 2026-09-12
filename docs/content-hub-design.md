# 内容中心（Content Hub）整合设计

> 状态：实施中（2026-08） · 目标：整合「资产 / 世界书 / 索引」三个模块为统一的内容管理体验
> 关联目标：内置方舟内容开箱即用 · 导入内容自由扩展 · 无重复入口 · 管理模式统一可解释

---

## 1. 现状梳理：三个模块的职责与重叠

| 模块 | 现有入口 | 职责 | 数据位置 | 可写 |
|---|---|---|---|---|
| 资产（DocumentManager） | 顶栏「资产」 | 文档树 + Markdown 编辑、图片资产管理、卡牌编辑、**文档依赖引用（imports）管理** | `data/<category>/`（git 跟踪） | 是 |
| 世界书（WorldBookManager） | 顶栏「世界书」 | 书 CRUD、酒馆格式导入（文件/粘贴）、条目编辑器、会话绑定、全局默认书 | `data/worldbooks/`（gitignored） | 是 |
| 索引（IndexManager） | 顶栏「索引」 | 文档关系图（imports）、会话索引白名单、断裂引用验证/修复、YAML 导入导出 | 读取 `data/<category>/` | 会话配置可写 |

**确认的功能重叠（同一能力多处实现 → 数据不一致风险）：**

1. **文档依赖引用管理**：DocumentManager 与 IndexManager 都提供「编辑某文档的 imports / 批量扫描 / 断裂引用检测修复」，走同一组 API（`GET/PUT /api/documents/<cat>/<id>/imports`、`scan`、`verify`），两套 UI、两套状态（DocumentManager 有自己的 brokenRefs 红点 + 批量扫描按钮，IndexManager 有全局 verify + 会话白名单依赖检查）。
2. **类别元数据**：`CATEGORY_LABELS` 在 DocumentManager 与 IndexManager 中各维护一份。
3. **会话级内容开关**：索引白名单（会话启用哪些实体）与文档编辑并存于不同页面，用户难以感知联动。

## 2. 统一管理模式

### 2.1 单一入口：内容中心

导航「资产 / 世界书 / 索引」三项合并为 **「内容中心」** 一项，内部按 Tab 组织：

| Tab | 内容 | 来源组件 |
|---|---|---|
| 角色·剧情（文档） | 文档树 + Markdown 编辑 + 图片/CSS 资源 | DocumentManager（docs Tab） |
| 世界书 | 书列表/导入/条目编辑/绑定 | WorldBookManager |
| 索引 | 关系图、会话白名单、断裂验证修复 | IndexManager |
| 资产 | 图片资产管理（上传/裁剪/默认图） | DocumentManager（images Tab） |
| 卡牌 | 卡牌编辑 | DocumentManager（cards Tab） |
| 战斗节点 | 战场地图/敌人编成/血量与难度编辑、剧情节拍进度 | BattleNodeEditor |

依赖引用编辑**收敛到索引 Tab**（它是关系图的天然位置）；文档 Tab 移除重复的 imports 编辑区块，保留查看入口。

### 2.2 统一管理模式：内容包（Content Pack），不做内置/导入分层

**核心决策（2026-08）：本家内容不做「内置只读层」，而是随程序分发一个整合包（Pack），与任何第三方内容在同一套管理规则下统一管理。**

| 来源 | 含义 | 存储 | 管理规则 |
|---|---|---|---|
| **预装（preinstalled）** | 随程序分发的方舟整合包，首次启动自动安装 | 分发源：`data/packs/*.json`（git 跟踪）；安装副本：`data/worldbooks/<id>.json`（gitignored） | 与导入内容**完全相同**：可编辑、可停用、可删除；删除后可从分发源一键「重装」 |
| **导入（imported）** | 用户导入/新建（第三方世界书、自制内容） | `data/worldbooks/*.json`（gitignored） | 完全可写 |

要点：

1. **存储统一**：所有书都在 `data/worldbooks/`，同一份列表、同一套 CRUD、同一个启用/停用开关——管理模式只有一套，可解释。
2. **开箱即用**：`WorldBookManager` 初始化时自动把 `data/packs/` 下的整合包复制到 `data/worldbooks/`（不存在才装），新用户零配置即有方舟世界书。
3. **来源标识（徽章）**：预装 = 青（可「重装」还原），导入 = 紫。仅作来源说明，不影响任何操作权限。
4. **程序 IP 中立**：用户可整体停用/卸载方舟整合包，导入自己的世界观内容，程序不绑定方舟。
5. 文档侧（角色/剧情/索引）属于程序内置故事内容（`data/<category>/`）；**角色卡导入**（SillyTavern 角色卡 PNG/JSON → `data/characters/<slug>/` + 内嵌世界书）已实现，frontmatter 带 `source: imported` 来源标识。

### 2.3 启用/停用语义统一

- **书级**：`WorldBook.enabled`（新增，默认 true）。停用的书不参与解析（resolve 跳过）。
- **条目级**：`entry.enabled`（已有）。
- **文档级**：会话索引白名单（已有）——启用哪些实体进入会话上下文。

### 2.4 开箱即用：方舟整合包

1. `scripts/generate_builtin_worldbook.py`：从 `data/characters/*/index.md`（角色名/别名/设定摘要）与 `data/plots/`（剧情概述）生成 `data/packs/arknights.json`（角色条目：触发词=角色名+别名；剧情条目：触发词=剧情名）。
2. 首次启动自动安装到 `data/worldbooks/arknights.json`（source=preinstalled）。
3. 解析回退链：**会话绑定 > 全局默认书 > 已启用的预装包（arknights）** —— 新用户零配置即有世界书生效。

### 2.5 统一检索

内容中心顶部全局搜索框：跨世界书书名/条目内容/条目触发词检索（后端新增 `GET /api/worldbook/search?q=`，文档侧复用现有 `/api/documents/search`）。

## 3. 接口变更

### 后端

- `GET /api/worldbook`：列表项新增 `source`（preinstalled/imported）、`is_preinstalled`、`enabled`。
- `GET /api/worldbook/<id>`：同上。
- `PUT /api/worldbook/<id>`：所有书均可更新（含 `enabled` 开关）；无只读限制。
- `DELETE /api/worldbook/<id>`：所有书均可删除（预装包删除后可用「重装」还原）。
- `POST /api/worldbook/<id>/reinstall`：从分发源重装预装整合包（恢复出厂内容）。
- `POST /api/worldbook/<id>/duplicate`：复制任意书为新导入书（做变体/备份）。
- `GET /api/worldbook/search?q=`：跨书/条目检索。
- `resolve`：回退到已安装且启用的预装包（`data/packs/` 分发源存在且 `data/worldbooks/` 中副本 enabled）。

### 前端

- `useApi`：`duplicateWorldbook`、`searchWorldbooks`、`updateWorldbook` 支持 enabled。
- 新组件 `ContentHub.tsx`、`SourceBadge.tsx`。
- `GameTopBar` / `HomeMenu`：三项导航合并为「内容中心」。
- `DocumentManager`：支持 `initialTab` prop；移除重复的 imports 编辑区块（保留轻量跳转）。

## 4. 验收对照

- [x] 新用户无需导入 → 方舟整合包自动安装，角色/剧情开箱即用
- [x] 第三方世界书与预装包共存于同一列表，来源徽章清晰可辨；可停用/卸载/重装
- [x] 无重复入口：内容中心单入口 + 依赖编辑收敛到索引
- [x] 统一检索、书级启用/停用、复制、重装

## 5. 数据模型（世界书存储格式）

分发源：`data/packs/<id>.json`（git 跟踪）→ 首次启动安装副本：`data/worldbooks/<id>.json`（gitignored）：

```json
{
  "id": "arknights",
  "name": "明日方舟·整合包",
  "source": "preinstalled",
  "enabled": true,
  "source_format": "builtin",
  "budget_tokens": 0,
  "entries": [ { "uid": "...", "name": "...", "content": "...", "trigger_keys": [...], ... } ]
}
```
