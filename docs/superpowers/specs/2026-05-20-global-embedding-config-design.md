# Global Embedding Config — Design Spec

**Date:** 2026-05-20  
**Status:** Approved

## Problem

Embedding model, API key, and API host are hardcoded or implicitly read from env vars. No way to set them persistently without editing env or source code.

## Goals

- Persist `embedding_model`, `api_key`, `api_base` in a global config file
- CLI commands to read/write config
- Support OpenAI and any OpenAI-compatible provider (Ollama, LM Studio, Together AI, etc.)
- Auto-derive `vector_size` from known models; require explicit value for unknown ones
- Detect vector size mismatch when model changes (before Qdrant fails)

## Out of Scope

- Per-repo model overrides
- Non-OpenAI-compatible providers (e.g., Cohere, HuggingFace native API)
- API key encryption / keychain integration

---

## Settings File

**Path:** `~/.codebase-mcp/settings.json`

```json
{
  "embedding_model": "text-embedding-3-small",
  "vector_size": 1536,
  "api_key": "sk-...",
  "api_base": "http://localhost:11434/v1"
}
```

All fields optional. File need not exist — defaults apply.

**Priority chain per field:**

| Field | Priority 1 | Priority 2 (fallback) | Default |
|-------|-----------|----------------------|---------|
| `api_key` | `settings.json` | `OPENAI_API_KEY` env var | error |
| `api_base` | `settings.json` | `OPENAI_BASE_URL` env var | OpenAI endpoint |
| `embedding_model` | `settings.json` | — | `text-embedding-3-small` |
| `vector_size` | `settings.json` | — | `1536` |

When `api_key=None` and `base_url=None` are passed to `OpenAI()`, the client reads env vars automatically — no extra code needed for fallback.

---

## New Module: `settings.py`

```python
from dataclasses import dataclass

KNOWN_MODELS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}

@dataclass
class Settings:
    embedding_model: str = "text-embedding-3-small"
    vector_size: int = 1536
    api_key: str | None = None
    api_base: str | None = None

def load_settings() -> Settings: ...
def save_settings(s: Settings) -> None: ...
def get_settings() -> Settings: ...  # load + apply defaults
```

---

## CLI Commands

Group: `codebase-mcp config`

### `config set`

```
codebase-mcp config set embedding-model <model> [--vector-size N]
codebase-mcp config set api-key <key>
codebase-mcp config set api-base <url>
```

`config set embedding-model` behavior:
- Model in `KNOWN_MODELS` → `vector_size` set automatically, `--vector-size` ignored
- Model unknown + `--vector-size N` provided → use N
- Model unknown + no `--vector-size` → exit with error: `Unknown model. Provide vector size: --vector-size 768`

### `config list`

Displays current settings. `api_key` masked: show first 5 chars + `***`.

```
embedding_model  text-embedding-3-small
vector_size      1536
api_key          sk-ab***
api_base         (not set)
```

### `config unset`

```
codebase-mcp config unset <key>
```

Removes field from `settings.json`. Value falls back to env var / default.

---

## Core Module Changes

### `store.py`

- Remove `VECTOR_SIZE = 1536`
- `ensure_collection(client, repo_id, vector_size: int)` — takes `vector_size` as parameter

### `indexer.py`

- `index_repo()` calls `get_settings()`, builds `OpenAI(api_key=s.api_key, base_url=s.api_base)`
- Passes `s.vector_size` to `ensure_collection()`
- `_embed_batch(texts, client, model)` — model passed as parameter, not hardcoded

### `searcher.py`

- `search()` calls `get_settings()`, builds `OpenAI(api_key=s.api_key, base_url=s.api_base)`
- Before querying each repo, checks collection vector size:
  ```python
  info = qdrant.get_collection(repo_id)
  actual = info.config.params.vectors.size
  if actual != settings.vector_size:
      # skip repo, append warning to results
      warnings.append(f"Mismatch in {path}: indexed with size {actual}, current model expects {settings.vector_size}. Run: codebase-mcp reindex {path}")
  ```
- Warnings prepended to the returned string (e.g. `"⚠ Mismatch in /path...\n\n### results..."`)
- If all repos mismatch, returns only the warning string (no search results)

---

## Files to Create / Modify

| Action | File |
|--------|------|
| Create | `src/codebase_mcp/settings.py` |
| Modify | `src/codebase_mcp/store.py` |
| Modify | `src/codebase_mcp/indexer.py` |
| Modify | `src/codebase_mcp/searcher.py` |
| Modify | `src/codebase_mcp/cli.py` |
| Create | `tests/test_settings.py` |
| Modify | `tests/test_indexer.py` |
| Modify | `tests/test_searcher.py` |

---

## Testing

- `test_settings.py`: load/save/defaults, `config set` known model, unknown model without `--vector-size`, `config unset`
- `test_indexer.py`: mock settings, verify `OpenAI` called with correct `api_key`/`base_url`/model
- `test_searcher.py`: mock mismatch scenario, verify warning returned
