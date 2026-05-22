# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run CLI app
python src/main.py

# Run Flask web API (listens on http://127.0.0.1:5000)
python src/app.py

# Install dependencies
pip install -r requirements.txt
```

## Project Architecture

Arknights text-based roleplay game with two interfaces (CLI + Flask API).

### Layer 1: LLM Backend (`src/load_llm.py`)
- **`LocalLLM`** — Ollama-based local inference (`/api/chat` endpoint)
- **`ApiLLM`** — OpenAI-compatible API (configured via `.env`: `API_KEY`, `API_URL`)
- Default API model is `Gemini-1.5-Flash` (can be changed in `ApiModelConfig`)
- Both expose `chat(messages, stream=False)` returning a string

### Layer 2: Character Agent (`src/CharacterAgent.py`)
- `CharacterAgent(name, llm)` loads a character markdown file from `data/characters/`
- Character files use YAML frontmatter + markdown body (parsed via `python-frontmatter`)
- Maintains `self.memory` (list of `{"role": "user"/"character", "content": ...}` dicts)
- Constructs a system prompt embedding character card + history, then calls the LLM

### Layer 3: Game Agent (`src/GameAgent.py`)
- Orchestrator that manages character switching, player info, and routing
- Tool-calling pattern: LLM responds with `<tool_call>{"name": ..., "arguments": {...}}</tool_call>` XML tags. GameAgent parses these, executes the tool, feeds result back to LLM.
- Available tools: `load_character`, `switch_character`, `load_player`, `exit_conversation`
- **Routing logic**: When a character is active, `_should_route_to_character()` asks the LLM whether the user input is character dialogue or a system command. Routes to `CharacterAgent.chat()` if character-directed.
- `_refine_response()` post-processes raw LLM output to strip tool tags and improve naturalness

### Data Files
- `data/characters/*.md` — Character definitions (YAML frontmatter with name, class, race, faction, tags, attributes, relationships + markdown body for backstory/personality/dialogue style)
- `environment/Location/Rhode_Island/*.md` — Location definitions
- `environment/weather/*.md` — Weather definitions with game-mechanics effects

## Important Notes

- `.env` contains API credentials — never commit it or expose it in output
- The README is outdated (references old file structure `agent.py`, `llm_loader.py` etc.)
- No test suite exists yet
- The `GameAgent.__init__()` takes no arguments (hardcoded to `ApiLLM`) — `app.py` and `main.py` both instantiate it with `GameAgent()`
- `app.py` caches `GameAgent` instances per `character_id` in a global dict — agent state persists across API requests
