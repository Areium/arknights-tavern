# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Backend (Python/Flask)
```bash
# Install dependencies
pip install -r requirements.txt

# Run API server (default http://127.0.0.1:5000)
python src/app.py

# With debug mode
FLASK_DEBUG=true python src/app.py

# Custom host/port
API_HOST=0.0.0.0 API_PORT=5000 python src/app.py
```

### Frontend (Electron + React + Vite)
```bash
# Install dependencies
cd frontend && npm install

# Development — Electron or web-only
cd frontend && npm run dev         # Electron dev
cd frontend && npm run dev:web     # Web-only (browser)

# Build
cd frontend && npm run build

# Preview build
cd frontend && npm run preview
```

## Git Workflow

Before implementing any major feature, follow this branch-based workflow:

1. **Create a feature branch** from `main` with a descriptive name (e.g., `feat/combat-ai`, `fix/memory-leak`)
2. **Make all changes** on the feature branch
3. **Test** the changes thoroughly to verify correctness
4. **Merge back to `main`** once tests pass
5. **Delete the feature branch** after a successful merge

Do not commit large feature changes directly to `main`.

## Project Architecture

### System Overview
An Arknights-themed text RPG with: story mode (LLM-driven narrative with choices, memory, and environment), free mode (sandbox character interaction), and a turn-based combat system on a 7×7 grid.

```
Electron + React (frontend/)
       │
       ▼
Flask API (src/app.py)
       │
       ├── SceneManager     — Multi-character scene management
       ├── CharacterAgent   — Character persona + VectorMemory
       ├── WikiManager      — Document indexing & query
       ├── DocumentManager  — File CRUD with hash-based conflict detection
       ├── SessionManager   — Multi-session lifecycle
       ├── LLMBackendManager — Multi-provider orchestration
       ├── EnvironmentState — Location/weather/time tracking
       ├── CombatSession    — Combat lifecycle management
       └── combat_engine/   — Turn-based grid combat engine
```

### Key Code Locations

**API Layer** (`src/blueprints/`): Flask Blueprints, one per resource domain:
- `chat.py` — Chat, group-chat, story narration, SSE streaming, structured-dialogue extraction, combat-trigger handling
- `scene.py` — Scene characters & items
- `combat.py` — Combat session CRUD & SSE push
- `documents.py` — Document CRUD, imports, search
- `sessions.py` — Session CRUD, rollback, index-config
- `environment.py` — Environment state
- `index.py` — Index overview, verify, export/import
- `wiki.py` — Wiki query
- `llm.py` — LLM config & status
- `assets.py` — Image upload
- `memories.py` — Story memory summaries
- `status.py` — Healthcheck endpoint

**Core Backend** (`src/`):
- `app.py` — Flask factory `create_app()`. Wires managers and blueprints
- `SceneManager.py` — Orchestrates CharacterAgents, builds shared context for multi-character scenes. Methods: `chat()`, `group_chat()`, load/unload/switch characters, scene items. Supports structured dialogue output (`parse_structured()`) for bubble-mode rendering
- `CharacterAgent.py` — Single character persona: system prompt construction with wiki context, memory injection, LLM interaction
- `session_manager.py` — Session lifecycle: create, history CRUD, rollback, narration variant storage. `combat_mode` ("narrative" | "tactical") is a Session-level property, set at creation time and immutable thereafter
- `session_overlay.py` — Per-session overrides for character/item properties, plot-log management (auto-truncates to last 15 entries), beat state tracking
- `session_context.py` — Caches document summaries per session
- `environment_state.py` — Environment state machine: location, weather, time transitions. Loads from `data/environment/` (entity-folder format)
- `wiki_manager.py` — Builds document catalog from `categories.yaml`, extracts core sections (summary/core/full), handles imports
- `document_manager.py` — File-level CRUD with hash-based conflict detection, search, folder management
- `index_manager.py` — Index overview, relation graph from `imports` fields, YAML export/import
- `memory.py` — `VectorMemory`: sliding window for recent turns + ChromaDB semantic search for history
- `llm_backend_manager.py` — Multi-provider detection, primary/fallback switching, auto-degradation
- `load_llm.py` — HTTP client for Ollama and OpenAI-compatible APIs, tool call parsing

**LLM Providers** (`src/providers/`):
- `base.py` — Abstract `ProviderAdapter` with interface for endpoint URL, auth, payload building, streaming/non-streaming response parsing
- `openai.py` — OpenAI-compatible API adapter (also serves as the `auto` default)
- `deepseek.py` — DeepSeek API adapter with reasoning_effort support (low/medium/high)

**Combat Engine** (`src/combat_engine/`):
- `engine.py` — Core turn loop, card resolution, AP management, morale
- `entity.py` — CombatUnit with HP, stats, buffs/debuffs
- `grid.py` — 7×7 grid pathfinding, ability range calculation, movement validation
- `card.py` — Card definition, target validation, damage calculation
- `card_data.py` — Full card database indexed by job class
- `dice.py` — Dice roll distribution functions (d20, 2d6, etc.)

**Frontend** (`frontend/src/`):
- `App.tsx` — Root layout with view routing (chat/documents/settings/combat/index) and 5s/10s polling loops for backend status, LLM status, session list
- `stores/appStore.ts` — Zustand store: current view, theme, chat mode, session, combat state, various refresh triggers (key-based, increment to signal reload)
- `hooks/useApi.ts` — API client: REST endpoints + SSE stream handlers with `connectSSE()` and `createPostSSE()` for streaming narration/chat
- `types/index.ts` — All TypeScript interfaces: Session, CombatUnit, CardDTO, SSEEvent, etc.

**Key Frontend Components:**
- `components/ChatPanel.tsx` — The main chat surface: messages, narration streaming, choices, narration variants, edit/delete/rollback, dialogue bubble mode
- `components/SessionList.tsx` — Session sidebar with CRUD, mode filtering, combat-mode selector (narrative/tactical) on story-session creation
- `components/combat/CombatView.tsx` — Full combat UI: grid, cards, status panels, event log (50k+ LOC, the largest component)
- `components/combat/CombatGrid.tsx` — 7×7 isometric 3D grid with drag-and-drop card targeting
- `components/DocumentManager.tsx` — Document tree browser + Markdown editor with frontmatter
- `components/SettingsPanel.tsx` — LLM config (multi-provider, reasoning_effort for DeepSeek), theme, narration options, max_output_tokens (256–16384, default 8192)

### Data Layer

**Document categories** defined in `data/categories.yaml` with hierarchy levels:
- Level 0: world, rules (global background)
- Level 1: attributes, races, classes, weather (base definitions)
- Level 2: factions, locations, items (world entities)
- Level 3: characters (actors)
- Level 4: plots, enemies, combat_encounters (narrative)
- Level 5: combat_enemies (combat components)

**Three-tier loading depth**: summary (~30 tokens from frontmatter) → core (~150 tokens from key sections) → full (~400 tokens, complete file). Controlled by `core_sections` in `constants.py`.

**Document references** via frontmatter `imports` field: `imports: [categories/doc-id | Display Name]`. Resolved by WikiManager.

### Communication Patterns

- **Polling**: Frontend polls `/api/status` (5s), `/api/llm/status` (10s), `/api/sessions` (15s), combat state (1s during combat)
- **SSE Streaming**: `POST /api/sessions/<id>/chat` and `/narrate-continue` stream tokens via SSE. Event types: `text`, `reasoning`, `scene_event`, `memory_event`, `choice`, `dialogue_segments`, `token_usage`, `combat_trigger`
- **Combat SSE**: Dedicated event stream at `/api/sessions/<id>/combat/events` for real-time combat updates
- **Key Refresh Pattern**: Zustand store uses incrementing integers as trigger keys — components poll and compare keys to detect stale data
