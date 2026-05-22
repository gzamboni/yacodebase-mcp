# Design: Agent Installer, Git Hook Monitor, Full Rename

Date: 2026-05-22  
Status: Approved

---

## Overview

Three independent features added to yacodebase-mcp:

1. **Agent Installer** — CLI commands to auto-configure the MCP server in major dev agents
2. **Git Hook Monitor** — post-commit hook for automatic incremental reindex
3. **Full Rename** — complete `codebase-mcp` → `yacodebase-mcp` rename

---

## Feature 1: Agent Installer

### Goal

`yacodebase-mcp install <agent>` writes the MCP server entry into a supported agent's global config file. Idempotent. Global scope (user-level config, active across all projects).

### CLI

```
yacodebase-mcp install claude-code [--dry-run]
yacodebase-mcp install cursor      [--dry-run]
yacodebase-mcp install windsurf    [--dry-run]
yacodebase-mcp install copilot     [--dry-run]
yacodebase-mcp install zed         [--dry-run]
yacodebase-mcp install opencode    [--dry-run]
yacodebase-mcp install all         [--dry-run]
yacodebase-mcp install status
```

`--dry-run`: print what would be written, no disk changes.  
`install status`: table showing each agent, config path, and whether codebase-search is already configured.

### New module: `src/codebase_mcp/agents.py`

Each agent is a dataclass/dict with:
- `name: str`
- `config_path() -> Path` (platform-aware: macOS/Linux)
- `read_config() -> dict`
- `write_config(data: dict) -> None`
- `merge_entry(data: dict, server_cmd: str) -> dict` — inserts MCP entry, idempotent by key
- `is_present() -> bool` — config file exists

### Supported agents, config paths, and MCP format

| Agent | Config path | MCP key | Entry format |
|---|---|---|---|
| `claude-code` | `~/.claude/settings.json` | `mcpServers` | `{command, args}` |
| `cursor` | `~/.cursor/mcp.json` | `mcpServers` | `{command, args}` |
| `windsurf` | `~/.codeium/windsurf/mcp_config.json` | `mcpServers` | `{command, args}` |
| `copilot` | macOS: `~/Library/Application Support/Code/User/settings.json`<br>Linux: `~/.config/Code/User/settings.json` | `mcp.servers` (nested) | `{type: stdio, command, args}` |
| `zed` | `~/.config/zed/settings.json` | `context_servers` | `{command: {path, args}}` |
| `opencode` | `~/.config/opencode/config.json` | `mcpServers` | `{command, args}` |

MCP server entry written (standard format):
```json
"codebase-search": {
  "command": "yacodebase-mcp",
  "args": ["serve"]
}
```

VS Code / Copilot adds `"type": "stdio"`.  
Zed wraps command: `"command": {"path": "yacodebase-mcp", "args": ["serve"]}`.

### Behavior rules

- Config file absent → create with just the MCP entry (parent dirs created as needed)
- Key `codebase-search` already present → overwrite (idempotent)
- `install all` → attempts all agents, reports success/skip/fail per agent, never aborts on first failure
- `install status` → table: agent | config path | installed (yes/no) | server command

### CLI additions to `cli.py`

```python
@main.group()
def install():
    """Configure MCP server in dev agent global settings."""

@install.command("claude-code")
@click.option("--dry-run", is_flag=True)
def install_claude_code(dry_run): ...

# ... one command per agent ...

@install.command("all")
@click.option("--dry-run", is_flag=True)
def install_all(dry_run): ...

@install.command("status")
def install_status(): ...
```

---

## Feature 2: Git Hook Monitor

### Goal

`yacodebase-mcp hook install <repo>` writes a `post-commit` hook that calls `yacodebase-mcp update` after every commit. Uses existing `index_repo_incremental()`.

### CLI

```
yacodebase-mcp hook install   [REPO_PATH]   # default: cwd
yacodebase-mcp hook uninstall [REPO_PATH]
yacodebase-mcp hook status    [REPO_PATH]   # default: all indexed repos
```

### Hook file

Written to `<repo>/.git/hooks/post-commit`:

```bash
#!/bin/sh
# yacodebase-mcp auto-reindex — do not remove this line
yacodebase-mcp update "$(git rev-parse --show-toplevel)"
```

File made executable (`chmod +x`) after write.

### Detection marker

`# yacodebase-mcp auto-reindex — do not remove this line`

Used to identify our block for safe removal and idempotency checks.

### Install behavior

| Condition | Action |
|---|---|
| Not a git repo | Error, abort |
| Hook file absent | Create file with shebang + our block |
| Hook file exists, no marker | Append our block at end of existing file |
| Hook file exists, marker present | No-op, print "already installed" |
| Repo not indexed | Warn: "hook installed; run `yacodebase-mcp index <path>` first" |

### Uninstall behavior

- Remove lines from marker line through end of our block
- If file is empty after removal → delete the file
- If file has other content → leave it intact

### `hook status` output

Table: repo path | hook installed (yes/no) | last indexed timestamp

### CLI additions to `cli.py`

```python
@main.group()
def hook():
    """Manage post-commit hooks for automatic reindex."""

@hook.command("install")
@click.argument("repo_path", default=".", type=click.Path(file_okay=False))
def hook_install(repo_path): ...

@hook.command("uninstall")
@click.argument("repo_path", default=".", type=click.Path(file_okay=False))
def hook_uninstall(repo_path): ...

@hook.command("status")
@click.argument("repo_path", required=False, type=click.Path(file_okay=False))
def hook_status(repo_path): ...
```

---

## Feature 3: Full Rename (`codebase-mcp` → `yacodebase-mcp`)

### Scope

Python module directory (`src/codebase_mcp/`) stays unchanged — renaming all internal imports is YAGNI.

### Changes by file

| File | Change |
|---|---|
| `pyproject.toml` | Add `yacodebase-mcp` entry point; keep `codebase-mcp` as deprecated silent alias; update GitHub URLs |
| `store.py` `_data_dir()` | Data dir `~/.codebase-mcp/` → `~/.yacodebase-mcp/`; auto-migrate on first run |
| `server.py` | Update `"Run: codebase-mcp …"` help strings throughout |
| `cli.py` | Update help strings |
| `README.md` | Title, body, install instructions |
| `CLAUDE.md` | Command references |

### Data directory migration

In `store._data_dir()`:

```python
old = Path.home() / ".codebase-mcp"
new = Path.home() / ".yacodebase-mcp"
if old.exists() and not new.exists():
    old.rename(new)
new.mkdir(parents=True, exist_ok=True)
return new
```

`Path.rename()` is atomic on same filesystem (home dir). Runs once on first use after upgrade.

### CLI alias and deprecation warning

```toml
[project.scripts]
yacodebase-mcp = "codebase_mcp.cli:main"
codebase-mcp   = "codebase_mcp.cli:main"
```

In `cli.py` `main()` entrypoint:

```python
import sys
if Path(sys.argv[0]).name == "codebase-mcp":
    click.echo("Warning: codebase-mcp is deprecated, use yacodebase-mcp", err=True)
```

---

## Out of scope

- Antigravity agent (insufficient public documentation on MCP config format)
- Filesystem watcher daemon (rejected in favor of git hook)
- Project-local agent install (global scope sufficient)
- Renaming Python module from `codebase_mcp` to `yacodebase_mcp`

---

## File changes summary

| File | Action |
|---|---|
| `src/codebase_mcp/agents.py` | **New** — agent registry + per-agent config read/write/merge |
| `src/codebase_mcp/cli.py` | **Modify** — add `install` group, `hook` group, deprecation warning |
| `src/codebase_mcp/store.py` | **Modify** — rename data dir + migration |
| `src/codebase_mcp/server.py` | **Modify** — update help strings |
| `pyproject.toml` | **Modify** — entry points + URLs |
| `README.md` | **Modify** — rename throughout |
| `CLAUDE.md` | **Modify** — rename throughout |
| `tests/test_agents.py` | **New** — unit tests for agents module |
| `tests/test_hook.py` | **New** — unit tests for hook install/uninstall |
