# yacodebase-mcp — dev guide

## Setup

```bash
uv sync
```

All commands use `uv run` (local venv shebang may point to a different path; always prefer `uv run python -m pytest` over `.venv/bin/pytest`).

## Run tests

```bash
uv run python -m pytest
uv run python -m pytest -v
uv run python -m pytest tests/test_ast_chunker.py -v   # specific module
```

## Lint / format

```bash
uv run ruff check src tests
uv run ruff format src tests
```

Line length: 100. Rules: E, F, I (pycodestyle, pyflakes, isort).

## Project structure

```
src/yacodebase_mcp/
  cli.py          # Click CLI: index, reindex, list, remove, serve, config, install, inject, hook, completion
  server.py       # FastMCP server — exposes search_codebase + list_indexed_repos
  indexer.py      # File walking, chunking, embedding, Qdrant upsert
  ast_chunker.py  # tree-sitter AST chunking (function/method boundaries)
  searcher.py     # Query embedding + Qdrant search + result formatting
  store.py        # Qdrant client, config.json r/w, repo metadata
  settings.py     # settings.json r/w (embedding model, vector size, api_key, api_base)
  agents.py       # Agent/InjectTarget dataclasses, AGENTS dict, INJECT_TARGETS dict, install_agent()
tests/
  test_agents.py
  test_ast_chunker.py
  test_cli.py
  test_indexer.py
  test_integration.py
  test_searcher.py
  test_settings.py
  test_store.py
```

## Key design decisions

**AST chunking → line fallback**: `indexer.chunk_file` tries `ast_chunker.chunk_file_ast` first. If the language is unsupported or tree-sitter fails, falls back to 100-line sliding window (20-line overlap). This ensures semantic boundaries for supported languages without breaking on unknown file types.

**In-process Qdrant**: No external service needed. `store.get_client()` returns a `QdrantClient` pointing at `~/.yacodebase-mcp/qdrant/`. One collection per repo, named by `repo_id` (hash of abs path).

**OpenAI-compatible embeddings**: `indexer` and `searcher` both instantiate `openai.OpenAI(api_key=..., base_url=...)` from settings. Any OpenAI-compatible provider works by setting `api_base`.

**Vector size mismatch detection**: `searcher.search` reads actual vector dim from Qdrant and skips repos where it doesn't match current model's `vector_size`. Emits a warning prompting reindex.

**MAX_CHUNK_CHARS = 16000**: Both `ast_chunker` and `indexer` truncate chunk text at 16k chars (~8192 tokens at 2 chars/token for dense code). Applied post-collection in `indexer.index_repo` as final safety.

**Config precedence**: `settings.json` fields override env vars. `api_key=None` in settings → falls back to `OPENAI_API_KEY` env var (handled by OpenAI SDK). `api_base=None` → uses OpenAI default.

**Absolute command path on install**: `agents._server_cmd()` resolves the binary via `shutil.which()` at install time. Written as an absolute path into agent configs so the server loads regardless of the agent's inherited `PATH`.

**TOML support for Codex CLI**: `Agent` dataclass has a `_format` field (`"json"` default, `"toml"` for Codex). `read_config`/`write_config` dispatch on it — uses stdlib `tomllib` for reading, `tomli_w` for writing. Codex config key is `mcp_servers` (not `mcpServers`).

**OS-aware install paths**: `_copilot_path()`, `_zed_path()`, and `_opencode_path()` branch on `sys.platform` (`"darwin"`, `"win32"`, else Linux). `cursor`, `windsurf`, and `claude-code` use `~/.xxx` paths which resolve correctly on all platforms via `Path.home()`.

**Inject / eject**: `InjectTarget` in `agents.py` writes a fenced instruction block (markers `<!-- yacodebase-mcp:start/end -->`) into agent rule files inside the repo (e.g. `CLAUDE.md`, `.cursor/rules/codebase-search.mdc`). Idempotent. `eject` removes only the marked block, preserving surrounding content.

## Adding a new language

1. Add tree-sitter grammar to `pyproject.toml` dependencies.
2. Add entry to `ast_chunker.EXT_TO_LANG` mapping extension → language name.
3. Add entry to `ast_chunker.SEMANTIC_NODES` mapping language → relevant node type set.
4. Add parser instantiation branch in `ast_chunker._get_parser`.
5. Add extension to `indexer.INDEXED_EXTENSIONS`.

## Adding a new install agent

1. Add path function and merge/check functions in `agents.py`.
2. Add entry to `AGENTS` dict with correct `_format` (`"json"` or `"toml"`).
3. Add `@install.command(...)` in `cli.py` calling `_do_install(name, dry_run)`.
4. Add entry to `INJECT_TARGETS` if the agent supports project-level rule files.
5. Update `test_all_agents_present` in `tests/test_agents.py`.

## Data dir

`~/.yacodebase-mcp/` — created on first use by `store._data_dir()`.

- `config.json` — repo registry: `{abs_path: {repo_id, chunk_count, last_indexed}}`
- `settings.json` — persistent settings (only non-null, non-default values written)
- `knowledge.db` — SQLite: decisions and notes
- `qdrant/` — Qdrant on-disk storage


<!-- yacodebase-mcp:start -->
## Codebase Search (yacodebase-mcp)

**First action every session: call `session_bootstrap`** — confirms the index is active and orients on recent changes before doing anything else.

This repository is indexed with yacodebase-mcp (semantic vector search over code).

- Prefer `search_codebase` MCP tool over grep/find for all code discovery.
- Use `search_codebase` when exploring unfamiliar code, finding usages, or locating implementations.
<!-- yacodebase-mcp:end -->
