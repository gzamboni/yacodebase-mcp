# Codebase Search MCP — Design Spec

**Date:** 2026-05-20  
**Status:** Approved

---

## Overview

MCP server that allows Claude to search any indexed codebase using vector similarity. Indexing is a manual CLI action controlled by the user. Claude only reads from the existing index — it never triggers re-indexing.

---

## Architecture

```
~/.codebase-mcp/
├── qdrant/          ← persistent vector index (Qdrant in-process)
└── config.json      ← indexed repos metadata (path, last_indexed, chunk_count)

~/Code/ai/codebase-mcp/
├── pyproject.toml
├── src/codebase_mcp/
│   ├── __init__.py
│   ├── cli.py        ← CLI entry point
│   ├── server.py     ← MCP server (FastMCP)
│   ├── indexer.py    ← chunking + embedding + upsert
│   ├── searcher.py   ← query embedding + vector search
│   └── store.py      ← Qdrant wrapper + config.json management
└── tests/
    └── test_integration.py
```

---

## Components

### CLI (`cli.py`)

Entry point: `codebase-mcp`

| Command | Description |
|---|---|
| `index <path>` | Index a repo. Fails if already indexed (use reindex). |
| `reindex <path>` | Remove old chunks, re-index from scratch. |
| `list` | Show all indexed repos with stats (chunk count, last indexed). |
| `remove <path>` | Delete repo from index. |
| `serve` | Start MCP server (used by Claude). |

### MCP Server (`server.py`)

Built with FastMCP. Exposes two tools to Claude:

**`search_codebase(query: str, repo_path: str | None) → str`**  
Embeds query, runs vector search, returns top 8 chunks with file path, line numbers, score, and content. If `repo_path` omitted, searches all indexed repos.

**`list_indexed_repos() → str`**  
Returns list of indexed repos with path, chunk count, and last indexed timestamp.

### Indexer (`indexer.py`)

- Walks repo files, skipping: `.git`, `node_modules`, `__pycache__`, `dist`, `build`, `.venv`, binaries
- Indexed extensions: `.py .ts .tsx .js .jsx .go .rs .rb .java .cpp .c .h .md .yaml .yml .toml .json`
- Chunking: sliding window, 100 lines, 20-line overlap
- Files <20 lines: single chunk
- Each chunk payload: `{ file, start_line, end_line, repo_path, repo_id }`
- Embeds in batches of 100 via OpenAI `text-embedding-3-small`
- Upserts to Qdrant collection named after `repo_id` (hash of absolute path)

### Searcher (`searcher.py`)

- Embeds query via OpenAI `text-embedding-3-small`
- Queries Qdrant for top 8 results (cosine similarity)
- Formats output as markdown blocks with file, lines, score

### Store (`store.py`)

- Qdrant client: in-process, data at `~/.codebase-mcp/qdrant/`
- Config at `~/.codebase-mcp/config.json`: maps `repo_path → { repo_id, last_indexed, chunk_count }`
- Creates `~/.codebase-mcp/` on first use

---

## Data Flow

### Indexing

```
codebase-mcp index /path/to/repo
  → validate path exists, not already indexed
  → walk files (apply extension + skip filters)
  → sliding window chunk (100L / 20L overlap)
  → batch embed via OpenAI API (100 chunks/batch, retry 3x on rate limit)
  → upsert to Qdrant (collection = repo_id)
  → write metadata to config.json
  → print summary: N files, M chunks, elapsed time
```

### Search (Claude)

```
search_codebase("how does auth work")
  → embed query via OpenAI
  → vector search Qdrant top 8 (across repo or all repos)
  → return formatted markdown: file, lines, score, content
```

---

## Error Handling

### CLI / Indexer

| Scenario | Behavior |
|---|---|
| Binary / undecodable file | Skip silently, log warning |
| OpenAI rate limit | Exponential backoff, 3 retries |
| `OPENAI_API_KEY` missing | Fail fast, clear message |
| Repo already indexed | Error: "already indexed, use `reindex`" |
| Path does not exist | Fail immediately with readable error |

### MCP Server

| Scenario | Behavior |
|---|---|
| Repo not indexed | Return: "not indexed — run: codebase-mcp index <path>" |
| OpenAI API failure on query | Propagate error to Claude with message |
| `repo_path` not found in index | Search all indexed repos instead |

---

## Dependencies

```toml
[project]
name = "codebase-mcp"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastmcp>=2.0",
    "qdrant-client>=1.9",
    "openai>=1.0",
    "click>=8.0",
    "rich>=13.0",
    "tiktoken>=0.7",
]

[project.scripts]
codebase-mcp = "codebase_mcp.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

---

## Installation & Claude Config

```bash
# install as uv tool
uv tool install /Users/gzamboni/Code/ai/codebase-mcp

# index a repo
codebase-mcp index ~/Code/ai/langfuse-mcp-server

# Claude config: ~/.claude/settings.json
{
  "mcpServers": {
    "codebase": {
      "command": "codebase-mcp",
      "args": ["serve"],
      "env": {
        "OPENAI_API_KEY": "sk-..."
      }
    }
  }
}
```

---

## Tests

Three integration tests in `tests/test_integration.py`:

1. **`test_index_and_search`** — index fixture repo, search, assert non-empty results
2. **`test_reindex_clears_old`** — index, reindex, confirm old chunks replaced
3. **`test_search_no_index`** — search unindexed repo, confirm correct error message

Tests use a temp directory for Qdrant data to avoid polluting `~/.codebase-mcp/`.

---

## Out of Scope

- Tree-sitter AST-based chunking (future improvement)
- Auto re-index on file change (watchdog daemon)
- Web UI for browsing index
- Remote Qdrant server
