# codebase-mcp

Vector search MCP server for codebases. Index repos locally, let Claude search them.

## Install

```bash
uv tool install /path/to/codebase-mcp
```

## Usage

```bash
# Index a repo
codebase-mcp index ~/Code/myproject

# Re-index after changes
codebase-mcp reindex ~/Code/myproject

# List indexed repos
codebase-mcp list

# Remove from index
codebase-mcp remove ~/Code/myproject
```

## Claude Code config

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "codebase": {
      "command": "codebase-mcp",
      "args": ["serve"],
      "env": { "OPENAI_API_KEY": "sk-..." }
    }
  }
}
```

## Data

Index stored at `~/.codebase-mcp/` (Qdrant in-process + config.json).
