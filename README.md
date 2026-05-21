# codebase-mcp

Vector search MCP server for codebases. Index repos locally with AST-aware chunking; let Claude (or any MCP client) search them semantically and query their structure.

## How it works

1. **Index** — walks repo files, chunks them using tree-sitter AST (function/method boundaries) with line-based fallback, embeds via OpenAI-compatible API, stores in in-process Qdrant.
2. **Serve** — exposes 12 MCP tools over stdio for search, structural analysis, and persistent knowledge.
3. **Search** — embeds the query, retrieves top-8 chunks across all indexed repos (or a specific one), returns ranked results with file path and line numbers.

## Install

```bash
pip install yacodebase-mcp
```

Or from source:

```bash
uv tool install /path/to/codebase-mcp
```

For development:

```bash
uv sync
```

## CLI

```bash
# Index a repo (fails if already indexed)
codebase-mcp index ~/Code/myproject

# Re-index after changes (replaces existing index)
codebase-mcp reindex ~/Code/myproject

# Incrementally update index (only changed files)
codebase-mcp update ~/Code/myproject

# List indexed repos with chunk counts
codebase-mcp list

# Remove a repo from the index
codebase-mcp remove ~/Code/myproject

# Start MCP server (stdio, used by Claude Code)
codebase-mcp serve
```

### Config commands

```bash
# Show current settings
codebase-mcp config list

# Set embedding model (known models auto-resolve vector size)
codebase-mcp config set embedding-model text-embedding-3-large
codebase-mcp config set embedding-model my-custom-model --vector-size 768

# Set API credentials
codebase-mcp config set api-key sk-...
codebase-mcp config set api-base https://my-provider.com/v1

# Revert a setting to default / env var fallback
codebase-mcp config unset embedding-model
codebase-mcp config unset api-key
codebase-mcp config unset api-base
```

**Known models** (vector size auto-detected):

| Model | Vector size |
|---|---|
| `text-embedding-3-small` | 1536 |
| `text-embedding-3-large` | 3072 |
| `text-embedding-ada-002` | 1536 |

Default: `text-embedding-3-small`.

## Claude Code config

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "codebase-search": {
      "command": "codebase-mcp",
      "args": ["serve"],
      "env": { "OPENAI_API_KEY": "sk-..." }
    }
  }
}
```

API key can also be set via `codebase-mcp config set api-key sk-...` (persisted in `~/.codebase-mcp/settings.json`), which takes precedence over the env var.

## MCP tools

### Search and navigation

#### `search_codebase`

Semantic search across indexed repos using embeddings.

| Parameter | Type | Description |
|---|---|---|
| `query` | string | Natural language description of what to find |
| `repo_path` | string (optional) | Absolute path to a specific repo; omit to search all |

Returns top-8 results ranked by similarity, each with file path, line range, score, and code block.

#### `get_file_outline`

Return the structural outline (functions, methods, classes) of a source file.

| Parameter | Type | Description |
|---|---|---|
| `file_path` | string | Absolute path to the source file |

#### `search_symbols`

Search for functions, methods, or classes by name across indexed repos.

| Parameter | Type | Description |
|---|---|---|
| `name` | string | Symbol name or substring (case-insensitive) |
| `repo_path` | string (optional) | Absolute path to a specific repo; omit to search all |

#### `find_todos`

Find TODO, FIXME, HACK, BUG, NOTE comments in indexed repos.

| Parameter | Type | Description |
|---|---|---|
| `repo_path` | string (optional) | Absolute path to a specific repo; omit to search all |

#### `what_changed`

Show files added or modified since the last index run.

| Parameter | Type | Description |
|---|---|---|
| `repo_path` | string (optional) | Absolute path to a specific repo; omit to check all |

#### `list_indexed_repos`

List all indexed repos with chunk count and last indexed timestamp. No parameters.

---

### Knowledge persistence

Architectural decisions and notes persist in a local SQLite database across sessions.

#### `add_decision`

Record an architectural decision.

| Parameter | Type | Description |
|---|---|---|
| `title` | string | Short title |
| `body` | string | Detailed explanation and rationale |
| `category` | string (optional) | e.g. `architecture`, `security`, `performance` |

#### `search_decisions`

Search recorded decisions by keyword or category.

| Parameter | Type | Description |
|---|---|---|
| `query` | string (optional) | Keyword to search in title and body |
| `category` | string (optional) | Filter by category |

#### `update_decision`

Update the status of a decision.

| Parameter | Type | Description |
|---|---|---|
| `decision_id` | int | ID from `search_decisions` output |
| `status` | string | `active`, `superseded`, `implemented`, or `rejected` |

#### `add_note`

Save a note that persists across sessions.

| Parameter | Type | Description |
|---|---|---|
| `content` | string | The note text |
| `scope` | string (optional) | `project`, `file`, or `symbol` |
| `reference` | string (optional) | File path or symbol name |

#### `get_notes`

Retrieve saved notes.

| Parameter | Type | Description |
|---|---|---|
| `scope` | string (optional) | Filter by scope; omit for all |

---

### Session orientation

#### `session_bootstrap`

Orient the agent at the start of a new session. Returns: indexed repos status, files changed since last index, active decisions, recent notes. Call this instead of reading files for orientation.

| Parameter | Type | Description |
|---|---|---|
| `repo_path` | string (optional) | Scope to a specific repo; omit for all |

---

## Supported languages (AST chunking)

| Language | Extensions | Chunk boundary |
|---|---|---|
| Python | `.py` | `function_definition`, `decorated_definition` |
| TypeScript | `.ts` | `function_declaration`, `method_definition`, `arrow_function` |
| TSX | `.tsx` | same as TypeScript |
| JavaScript | `.js`, `.jsx` | `function_declaration`, `method_definition`, `arrow_function` |
| Go | `.go` | `function_declaration`, `method_declaration` |
| Rust | `.rs` | `function_item` |
| Java | `.java` | `method_declaration`, `constructor_declaration` |
| HCL/Terraform | `.tf` | `block` |

Files without AST support (`.md`, `.yaml`, `.toml`, `.json`, `.rb`, `.cpp`, `.c`, `.h`) fall back to 100-line sliding window with 20-line overlap.

## Data storage

All data lives in `~/.codebase-mcp/`:

```
~/.codebase-mcp/
  config.json      # indexed repo metadata (paths, repo_ids, chunk counts, file hashes, timestamps)
  settings.json    # embedding model, vector size, api_key, api_base
  knowledge.db     # SQLite: architectural decisions and notes
  qdrant/          # Qdrant in-process storage (one collection per repo)
```

Each repo gets a stable `repo_id` derived from its absolute path (used as Qdrant collection name). Reindexing replaces the collection in-place. Incremental updates (`codebase-mcp update`) use SHA256 hashes to skip unchanged files.

## OpenAI-compatible providers

Set `api-base` to use any OpenAI-compatible embedding API (e.g. Ollama, vLLM, Azure):

```bash
codebase-mcp config set api-base http://localhost:11434/v1
codebase-mcp config set api-key ollama
codebase-mcp config set embedding-model nomic-embed-text --vector-size 768
```

After changing the model, reindex all repos (vector dimensions must match).
