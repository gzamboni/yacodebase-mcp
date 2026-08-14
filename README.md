# yacodebase-mcp

Vector search MCP server for codebases. Index repos locally with AST-aware chunking; let Claude (or any MCP client) search them semantically and query their structure.

## How it works

1. **Index** — walks repo files, chunks them using tree-sitter AST (function/method boundaries) with line-based fallback, embeds via OpenAI-compatible API, stores in in-process Qdrant. Indexes are branch-aware: each git branch gets its own collection, so switching branches doesn't overwrite another branch's index.
2. **Serve** — exposes 12 MCP tools over stdio for search, structural analysis, and persistent knowledge.
3. **Search** — embeds the query, retrieves top-8 chunks across all indexed repos (or a specific one), returns ranked results with file path and line numbers.

## Install

```bash
pip install yacodebase-mcp
```

Or from source:

```bash
uv tool install /path/to/yacodebase-mcp
```

For development:

```bash
uv sync
```

## CLI

```bash
# Show version
yacodebase-mcp --version

# Index a repo (fails if already indexed)
yacodebase-mcp index ~/Code/myproject

# Re-index after changes (replaces existing index)
yacodebase-mcp reindex ~/Code/myproject

# Incrementally update index (only changed files)
yacodebase-mcp update ~/Code/myproject

# List indexed repos with chunk counts
yacodebase-mcp list

# Remove a repo from the index
yacodebase-mcp remove ~/Code/myproject

# Start MCP server (stdio, used by Claude Code)
yacodebase-mcp serve
```

### Config commands

```bash
# Show current settings
yacodebase-mcp config list

# Set embedding model (known models auto-resolve vector size)
yacodebase-mcp config set embedding-model text-embedding-3-large
yacodebase-mcp config set embedding-model my-custom-model --vector-size 768

# Set API credentials
yacodebase-mcp config set api-key sk-...
yacodebase-mcp config set api-base https://my-provider.com/v1

# Revert a setting to default / env var fallback
yacodebase-mcp config unset embedding-model
yacodebase-mcp config unset api-key
yacodebase-mcp config unset api-base
```

**Known models** (vector size auto-detected):

| Model | Vector size |
|---|---|
| `text-embedding-3-small` | 1536 |
| `text-embedding-3-large` | 3072 |
| `text-embedding-ada-002` | 1536 |

Default: `text-embedding-3-small`.

## Agent installation

Install the MCP server config into your dev agent's global settings with a single command. The installer resolves the absolute path to the binary so it loads regardless of the agent's `PATH`.

```bash
# Install into a specific agent
yacodebase-mcp install claude-code
yacodebase-mcp install cursor
yacodebase-mcp install windsurf
yacodebase-mcp install copilot        # GitHub Copilot (VS Code)
yacodebase-mcp install zed
yacodebase-mcp install opencode
yacodebase-mcp install codex          # OpenAI Codex CLI

# Install into all supported agents at once
yacodebase-mcp install all

# Preview changes without writing
yacodebase-mcp install claude-code --dry-run

# Check installation status
yacodebase-mcp install status
```

Config paths per agent and OS:

| Agent | macOS | Linux | Windows |
|---|---|---|---|
| Claude Code | `~/.claude.json` | same | same |
| Cursor | `~/.cursor/mcp.json` | same | same |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` | same | same |
| Copilot (VS Code) | `~/Library/Application Support/Code/User/settings.json` | `~/.config/Code/User/settings.json` | `%APPDATA%\Code\User\settings.json` |
| Zed | `~/.config/zed/settings.json` | same | `%APPDATA%\Zed\settings.json` |
| OpenCode | `~/.config/opencode/config.json` | same | `%APPDATA%\opencode\config.json` |
| Codex CLI | `~/.codex/config.toml` | same | same |

## Inject agent instructions (ensure always used)

Even with the MCP server installed globally, agents need explicit guidance to use `search_codebase` in a specific repo. The `inject` command writes instruction blocks into agent rule files inside the repo itself.

```bash
# Inject instructions for all agents into current repo
yacodebase-mcp inject run

# Inject for specific agents only
yacodebase-mcp inject run ~/Code/myproject --agent claude-code --agent cursor

# Preview without writing
yacodebase-mcp inject run --dry-run

# Remove injected instructions
yacodebase-mcp inject eject

# Check injection status
yacodebase-mcp inject status
```

Files written per agent:

| Agent | File |
|---|---|
| Claude Code | `CLAUDE.md` |
| Cursor | `.cursor/rules/codebase-search.mdc` |
| GitHub Copilot | `.github/copilot-instructions.md` |
| Codex CLI | `.codex/instructions.md` |

The injected block is idempotent (fenced with marker comments) and appends to existing content. `eject` removes only the injected block, leaving surrounding content intact.

**Recommended workflow after indexing:**

```bash
yacodebase-mcp index ~/Code/myproject
yacodebase-mcp inject run ~/Code/myproject
```

## Shell completions

```bash
# bash — add to ~/.bashrc
source <(yacodebase-mcp completion bash)

# zsh — add to ~/.zshrc
source <(yacodebase-mcp completion zsh)

# fish — add to ~/.config/fish/config.fish
yacodebase-mcp completion fish | source
```

## Manual Claude Code config

Add to `~/.claude.json` at the top level (or use `yacodebase-mcp install claude-code`):

```json
{
  "mcpServers": {
    "codebase-search": {
      "type": "stdio",
      "command": "/path/to/yacodebase-mcp",
      "args": ["serve"],
      "env": {}
    }
  }
}
```

API key can also be set via `yacodebase-mcp config set api-key sk-...` (persisted in `~/.yacodebase-mcp/settings.json`), which takes precedence over the env var.

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

All data lives in `~/.yacodebase-mcp/`:

```
~/.yacodebase-mcp/
  config.json      # indexed repo metadata (paths, repo_ids, chunk counts, file hashes, timestamps)
  settings.json    # embedding model, vector size, api_key, api_base
  knowledge.db     # SQLite: architectural decisions and notes
  qdrant/          # Qdrant in-process storage (one collection per repo)
```

Each repo gets a stable `repo_id` derived from its absolute path plus current git branch (`path#branch`, used as Qdrant collection name) — outside a git repo, or on detached HEAD, it falls back to the bare path. Reindexing replaces the collection in-place. Incremental updates (`yacodebase-mcp update`) use SHA256 hashes to skip unchanged files, scoped per branch.

### Branches

Indexing is branch-scoped: `yacodebase-mcp index`/`update` always target the branch currently checked out, and `search`/MCP tools only see whichever branches have been indexed. To keep multiple branches searchable at once, index each one after checking it out:

```bash
git checkout main
yacodebase-mcp index ~/Code/myproject

git checkout feature-x
yacodebase-mcp index ~/Code/myproject
```

`yacodebase-mcp list` shows the branch each entry belongs to. `remove <path>` only removes the entry for the currently checked-out branch; if the repo is indexed under a different branch, it tells you which one instead of failing silently.

If you use `git worktree` instead, each worktree already has its own directory (and thus its own `repo_id`) — no branch-suffix needed, it just works.

## OpenAI-compatible providers

Set `api-base` to use any OpenAI-compatible embedding API (e.g. Ollama, vLLM, Azure):

```bash
yacodebase-mcp config set api-base http://localhost:11434/v1
yacodebase-mcp config set api-key ollama
yacodebase-mcp config set embedding-model nomic-embed-text --vector-size 768
```

After changing the model, reindex all repos (vector dimensions must match).
