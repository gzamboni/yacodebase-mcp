# Agent Installer, Git Hook Monitor, Full Rename — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `yacodebase-mcp install <agent>` and `hook` CLI subgroups for one-command dev agent setup and auto-reindex on commit, while completing the full `codebase-mcp → yacodebase-mcp` rename.

**Architecture:** New `agents.py` module owns per-agent config read/write/merge logic; new `hook.py` owns git hook install/uninstall/status logic; both are wired into `cli.py` as Click subgroups. The rename is purely mechanical: entry point, data dir (with one-time migration), and strings.

**Tech Stack:** Python 3.11+, Click 8, Rich, pathlib, json, stat (stdlib only for new modules)

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `src/codebase_mcp/agents.py` | **Create** | Agent registry; per-agent config path, read, write, merge, check |
| `src/codebase_mcp/hook.py` | **Create** | Hook install/uninstall/status logic |
| `src/codebase_mcp/cli.py` | **Modify** | Add `install` group, `hook` group, deprecation warning |
| `src/codebase_mcp/store.py` | **Modify** | Data dir rename + one-time migration |
| `src/codebase_mcp/server.py` | **Modify** | Update `"codebase-mcp"` help strings |
| `pyproject.toml` | **Modify** | Add `yacodebase-mcp` entry point + keep alias, update URLs |
| `README.md` | **Modify** | Rename throughout |
| `CLAUDE.md` | **Modify** | Rename throughout |
| `tests/test_store.py` | **Modify** | Add migration tests |
| `tests/test_agents.py` | **Create** | Unit tests for agents module |
| `tests/test_hook.py` | **Create** | Unit tests for hook module |

---

## Task 1: Data Dir Rename + Migration (`store.py`)

**Files:**
- Modify: `src/codebase_mcp/store.py:11-12`
- Modify: `tests/test_store.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_store.py` (after existing tests):

```python
def test_data_dir_migrates_old_to_new(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.delenv("CODEBASE_MCP_DATA_DIR", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    old = tmp_path / ".codebase-mcp"
    old.mkdir()
    (old / "config.json").write_text("{}")

    from codebase_mcp.store import _data_dir

    result = _data_dir()
    assert result == tmp_path / ".yacodebase-mcp"
    assert (result / "config.json").exists()
    assert not old.exists()


def test_data_dir_no_old_dir(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.delenv("CODEBASE_MCP_DATA_DIR", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    from codebase_mcp.store import _data_dir

    result = _data_dir()
    assert result == tmp_path / ".yacodebase-mcp"


def test_data_dir_env_var_wins(tmp_path, monkeypatch):
    custom = str(tmp_path / "custom-data")
    monkeypatch.setenv("CODEBASE_MCP_DATA_DIR", custom)

    from codebase_mcp.store import _data_dir

    assert _data_dir() == Path(custom)
```

- [ ] **Step 2: Run to confirm failure**

```
.venv/bin/pytest tests/test_store.py::test_data_dir_migrates_old_to_new -v
```

Expected: `FAILED` — `AssertionError` because result is still `.codebase-mcp`.

- [ ] **Step 3: Implement migration in `store.py`**

Replace lines 11–12:

```python
# Before
def _data_dir() -> Path:
    return Path(os.environ.get("CODEBASE_MCP_DATA_DIR", str(Path.home() / ".codebase-mcp")))
```

```python
# After
def _data_dir() -> Path:
    override = os.environ.get("CODEBASE_MCP_DATA_DIR")
    if override:
        return Path(override)
    old = Path.home() / ".codebase-mcp"
    new = Path.home() / ".yacodebase-mcp"
    if old.exists() and not new.exists():
        old.rename(new)
    return new
```

- [ ] **Step 4: Run all store tests**

```
.venv/bin/pytest tests/test_store.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/codebase_mcp/store.py tests/test_store.py
git commit -m "feat: rename data dir .codebase-mcp → .yacodebase-mcp with auto-migration"
```

---

## Task 2: Mechanical String Rename

**Files:**
- Modify: `src/codebase_mcp/server.py`
- Modify: `src/codebase_mcp/cli.py`
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `CLAUDE.md`

No new tests. Run full test suite after to confirm nothing broke.

- [ ] **Step 1: Update `server.py` help strings**

Replace every occurrence of `codebase-mcp` with `yacodebase-mcp` in the tool docstrings and return strings inside `server.py`. Affected lines: the `list_indexed_repos`, `search_symbols`, `find_todos` return strings that say `"Run: codebase-mcp index /path/to/repo"`.

```python
# Every instance of this pattern:
return "No repos indexed. Run: codebase-mcp index /path/to/repo"
# becomes:
return "No repos indexed. Run: yacodebase-mcp index /path/to/repo"
```

There are four such strings in `server.py` (in `list_indexed_repos`, `search_symbols`, `find_todos`, `session_bootstrap`). Update all four.

- [ ] **Step 2: Update `cli.py` help strings**

In `cli.py`, update the group docstring and any `click.echo` / `console.print` strings containing `codebase-mcp`:

```python
# cli.py line 16 — group docstring
"""Codebase vector search — index repos, search via MCP."""
# no change needed here (no tool name in this string)

# cli.py line 50-51 — update command
click.echo(f"Not indexed. Run: codebase-mcp index {repo_path}", err=True)
# becomes:
click.echo(f"Not indexed. Run: yacodebase-mcp index {repo_path}", err=True)
```

- [ ] **Step 3: Add `yacodebase-mcp` entry point + deprecation warning to `pyproject.toml` and `cli.py`**

In `pyproject.toml`, replace the `[project.scripts]` section:

```toml
[project.scripts]
yacodebase-mcp = "codebase_mcp.cli:main"
codebase-mcp   = "codebase_mcp.cli:main"
```

In `pyproject.toml`, update the URLs:

```toml
[project.urls]
Homepage   = "https://github.com/gzamboni/yacodebase-mcp"
Repository = "https://github.com/gzamboni/yacodebase-mcp"
Issues     = "https://github.com/gzamboni/yacodebase-mcp/issues"
```

In `cli.py`, add deprecation warning to the `main` group function:

```python
@click.group()
def main():
    """Codebase vector search — index repos, search via MCP."""
    import sys
    if Path(sys.argv[0]).name == "codebase-mcp":
        click.echo("Warning: codebase-mcp is deprecated, use yacodebase-mcp", err=True)
```

- [ ] **Step 4: Update `README.md`**

Replace all occurrences of `codebase-mcp` with `yacodebase-mcp` in `README.md`, except in the `# codebase-mcp` title which should become `# yacodebase-mcp`. Also update the install command from `pip install yacodebase-mcp` (already correct) and the `uv tool install` note.

Key replacements:
- `# codebase-mcp` → `# yacodebase-mcp`
- All `codebase-mcp index`, `codebase-mcp serve`, `codebase-mcp list`, etc. → `yacodebase-mcp …`
- `codebase-mcp serve` in MCP config examples → `yacodebase-mcp serve`

- [ ] **Step 5: Update `CLAUDE.md`**

Replace all `codebase-mcp` command references with `yacodebase-mcp` in `CLAUDE.md`. The Python package path `codebase_mcp` (underscores) stays unchanged.

- [ ] **Step 6: Run full test suite**

```
.venv/bin/pytest -v
```

Expected: all PASS (string changes don't affect logic tests).

- [ ] **Step 7: Commit**

```bash
git add src/codebase_mcp/server.py src/codebase_mcp/cli.py pyproject.toml README.md CLAUDE.md
git commit -m "feat: rename CLI command and strings codebase-mcp → yacodebase-mcp"
```

---

## Task 3: `agents.py` Module

**Files:**
- Create: `src/codebase_mcp/agents.py`
- Create: `tests/test_agents.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_agents.py`:

```python
import json
import sys
from pathlib import Path

import pytest


@pytest.fixture
def agent_config_dir(tmp_path, monkeypatch):
    """Patch Path.home so all agent config paths point into tmp_path."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


def test_claude_code_config_path(agent_config_dir):
    from codebase_mcp.agents import AGENTS

    expected = agent_config_dir / ".claude" / "settings.json"
    assert AGENTS["claude-code"].config_path() == expected


def test_install_creates_config(agent_config_dir):
    from codebase_mcp.agents import AGENTS, MCP_SERVER_NAME, install_agent

    agent = AGENTS["claude-code"]
    result = install_agent(agent)
    assert result == "installed"
    data = json.loads(agent.config_path().read_text())
    assert MCP_SERVER_NAME in data["mcpServers"]
    assert data["mcpServers"][MCP_SERVER_NAME]["command"] == "yacodebase-mcp"
    assert data["mcpServers"][MCP_SERVER_NAME]["args"] == ["serve"]


def test_install_idempotent(agent_config_dir):
    from codebase_mcp.agents import AGENTS, install_agent

    agent = AGENTS["claude-code"]
    install_agent(agent)
    result = install_agent(agent)
    assert result == "already"


def test_install_dry_run_no_write(agent_config_dir):
    from codebase_mcp.agents import AGENTS, install_agent

    agent = AGENTS["claude-code"]
    result = install_agent(agent, dry_run=True)
    assert result == "dry_run"
    assert not agent.config_path().exists()


def test_install_merges_existing_config(agent_config_dir):
    from codebase_mcp.agents import AGENTS, MCP_SERVER_NAME, install_agent

    agent = AGENTS["claude-code"]
    agent.config_path().parent.mkdir(parents=True, exist_ok=True)
    agent.config_path().write_text(json.dumps({"other_setting": True}))

    install_agent(agent)
    data = json.loads(agent.config_path().read_text())
    assert data["other_setting"] is True
    assert MCP_SERVER_NAME in data["mcpServers"]


def test_vscode_format(agent_config_dir):
    from codebase_mcp.agents import AGENTS, MCP_SERVER_NAME, install_agent

    agent = AGENTS["copilot"]
    install_agent(agent)
    data = json.loads(agent.config_path().read_text())
    entry = data["mcp"]["servers"][MCP_SERVER_NAME]
    assert entry["type"] == "stdio"
    assert entry["command"] == "yacodebase-mcp"


def test_zed_format(agent_config_dir):
    from codebase_mcp.agents import AGENTS, MCP_SERVER_NAME, install_agent

    agent = AGENTS["zed"]
    install_agent(agent)
    data = json.loads(agent.config_path().read_text())
    entry = data["context_servers"][MCP_SERVER_NAME]
    assert entry["command"]["path"] == "yacodebase-mcp"
    assert entry["command"]["args"] == ["serve"]


def test_is_installed_false_when_absent(agent_config_dir):
    from codebase_mcp.agents import AGENTS

    assert AGENTS["claude-code"].is_installed() is False


def test_is_installed_true_after_install(agent_config_dir):
    from codebase_mcp.agents import AGENTS, install_agent

    agent = AGENTS["cursor"]
    install_agent(agent)
    assert agent.is_installed() is True


def test_all_agents_present():
    from codebase_mcp.agents import AGENTS

    expected = {"claude-code", "cursor", "windsurf", "copilot", "zed", "opencode"}
    assert set(AGENTS.keys()) == expected
```

- [ ] **Step 2: Run to confirm failure**

```
.venv/bin/pytest tests/test_agents.py -v
```

Expected: `ERROR` — `ModuleNotFoundError: No module named 'codebase_mcp.agents'`

- [ ] **Step 3: Create `src/codebase_mcp/agents.py`**

```python
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

MCP_SERVER_NAME = "codebase-search"
MCP_SERVER_CMD = "yacodebase-mcp"
MCP_SERVER_ARGS = ["serve"]


@dataclass
class Agent:
    name: str
    label: str
    _get_path: Callable[[], Path] = field(repr=False)
    _merge_fn: Callable[[dict], dict] = field(repr=False)
    _check_fn: Callable[[dict], bool] = field(repr=False)

    def config_path(self) -> Path:
        return self._get_path()

    def is_present(self) -> bool:
        return self.config_path().exists()

    def read_config(self) -> dict:
        p = self.config_path()
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            return {}

    def write_config(self, data: dict) -> None:
        p = self.config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2) + "\n")

    def is_installed(self) -> bool:
        return self._check_fn(self.read_config())

    def merge(self, data: dict) -> dict:
        return self._merge_fn(data)


def _std_entry() -> dict:
    return {"command": MCP_SERVER_CMD, "args": MCP_SERVER_ARGS}


def _merge_mcpservers(data: dict) -> dict:
    data.setdefault("mcpServers", {})[MCP_SERVER_NAME] = _std_entry()
    return data


def _check_mcpservers(data: dict) -> bool:
    return MCP_SERVER_NAME in data.get("mcpServers", {})


def _merge_vscode(data: dict) -> dict:
    entry = {"type": "stdio", "command": MCP_SERVER_CMD, "args": MCP_SERVER_ARGS}
    data.setdefault("mcp", {}).setdefault("servers", {})[MCP_SERVER_NAME] = entry
    return data


def _check_vscode(data: dict) -> bool:
    return MCP_SERVER_NAME in data.get("mcp", {}).get("servers", {})


def _merge_zed(data: dict) -> dict:
    data.setdefault("context_servers", {})[MCP_SERVER_NAME] = {
        "command": {"path": MCP_SERVER_CMD, "args": MCP_SERVER_ARGS}
    }
    return data


def _check_zed(data: dict) -> bool:
    return MCP_SERVER_NAME in data.get("context_servers", {})


def _copilot_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Code" / "User" / "settings.json"
    return Path.home() / ".config" / "Code" / "User" / "settings.json"


AGENTS: dict[str, Agent] = {
    "claude-code": Agent(
        name="claude-code",
        label="Claude Code",
        _get_path=lambda: Path.home() / ".claude" / "settings.json",
        _merge_fn=_merge_mcpservers,
        _check_fn=_check_mcpservers,
    ),
    "cursor": Agent(
        name="cursor",
        label="Cursor",
        _get_path=lambda: Path.home() / ".cursor" / "mcp.json",
        _merge_fn=_merge_mcpservers,
        _check_fn=_check_mcpservers,
    ),
    "windsurf": Agent(
        name="windsurf",
        label="Windsurf",
        _get_path=lambda: Path.home() / ".codeium" / "windsurf" / "mcp_config.json",
        _merge_fn=_merge_mcpservers,
        _check_fn=_check_mcpservers,
    ),
    "copilot": Agent(
        name="copilot",
        label="GitHub Copilot (VS Code)",
        _get_path=_copilot_path,
        _merge_fn=_merge_vscode,
        _check_fn=_check_vscode,
    ),
    "zed": Agent(
        name="zed",
        label="Zed",
        _get_path=lambda: Path.home() / ".config" / "zed" / "settings.json",
        _merge_fn=_merge_zed,
        _check_fn=_check_zed,
    ),
    "opencode": Agent(
        name="opencode",
        label="OpenCode",
        _get_path=lambda: Path.home() / ".config" / "opencode" / "config.json",
        _merge_fn=_merge_mcpservers,
        _check_fn=_check_mcpservers,
    ),
}


def install_agent(agent: Agent, dry_run: bool = False) -> str:
    """Install MCP server entry into agent config. Returns 'already', 'dry_run', or 'installed'."""
    if agent.is_installed():
        return "already"
    data = agent.read_config()
    new_data = agent.merge(data)
    if dry_run:
        return "dry_run"
    agent.write_config(new_data)
    return "installed"
```

- [ ] **Step 4: Run tests**

```
.venv/bin/pytest tests/test_agents.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/codebase_mcp/agents.py tests/test_agents.py
git commit -m "feat: add agents module with per-agent MCP config install logic"
```

---

## Task 4: `install` CLI Group

**Files:**
- Modify: `src/codebase_mcp/cli.py`

No new test file — CLI wiring is thin; covered by agents.py tests. Smoke-test manually.

- [ ] **Step 1: Add `import json` to `cli.py`**

At the top of `cli.py`, add `import json` after the existing `from pathlib import Path` line:

```python
from pathlib import Path

import click
import json
from rich.console import Console
from rich.table import Table
```

- [ ] **Step 2: Add `install` group and helper to `cli.py`**

Add after the existing `config` group at the bottom of `cli.py`:

```python
@main.group()
def install():
    """Install MCP server config in dev agent global settings."""


def _do_install(agent_name: str, dry_run: bool) -> None:
    from .agents import AGENTS, install_agent

    agent = AGENTS[agent_name]
    status = install_agent(agent, dry_run=dry_run)
    path = str(agent.config_path())
    if status == "already":
        console.print(f"[yellow]Already configured: {path}[/yellow]")
    elif status == "dry_run":
        data = agent.read_config()
        new_data = agent.merge(data)
        console.print(f"[bold]Would write to {path}:[/bold]")
        console.print(json.dumps(new_data, indent=2))
    else:
        console.print(f"[green]Installed: {path}[/green]")


@install.command("claude-code")
@click.option("--dry-run", is_flag=True, help="Print changes without writing.")
def install_claude_code(dry_run: bool) -> None:
    """Install MCP config for Claude Code."""
    _do_install("claude-code", dry_run)


@install.command("cursor")
@click.option("--dry-run", is_flag=True)
def install_cursor(dry_run: bool) -> None:
    """Install MCP config for Cursor."""
    _do_install("cursor", dry_run)


@install.command("windsurf")
@click.option("--dry-run", is_flag=True)
def install_windsurf(dry_run: bool) -> None:
    """Install MCP config for Windsurf."""
    _do_install("windsurf", dry_run)


@install.command("copilot")
@click.option("--dry-run", is_flag=True)
def install_copilot(dry_run: bool) -> None:
    """Install MCP config for GitHub Copilot (VS Code)."""
    _do_install("copilot", dry_run)


@install.command("zed")
@click.option("--dry-run", is_flag=True)
def install_zed(dry_run: bool) -> None:
    """Install MCP config for Zed."""
    _do_install("zed", dry_run)


@install.command("opencode")
@click.option("--dry-run", is_flag=True)
def install_opencode(dry_run: bool) -> None:
    """Install MCP config for OpenCode."""
    _do_install("opencode", dry_run)


@install.command("all")
@click.option("--dry-run", is_flag=True, help="Print changes without writing.")
def install_all(dry_run: bool) -> None:
    """Install MCP config in all supported dev agents."""
    from .agents import AGENTS, install_agent

    for name, agent in AGENTS.items():
        status = install_agent(agent, dry_run=dry_run)
        path = str(agent.config_path())
        if status == "already":
            console.print(f"[yellow]{name}: already configured ({path})[/yellow]")
        elif status == "dry_run":
            console.print(f"[cyan]{name}: would write to {path}[/cyan]")
        else:
            console.print(f"[green]{name}: installed ({path})[/green]")


@install.command("status")
def install_status() -> None:
    """Show MCP config install status for all supported dev agents."""
    from .agents import AGENTS

    table = Table(show_header=True, expand=False)
    table.add_column("Agent", no_wrap=True)
    table.add_column("Config path", overflow="fold")
    table.add_column("Installed")

    for agent in AGENTS.values():
        installed = "[green]yes[/green]" if agent.is_installed() else "[red]no[/red]"
        table.add_row(agent.label, str(agent.config_path()), installed)

    wide_console = Console(width=10000)
    wide_console.print(table)
```

- [ ] **Step 3: Smoke-test CLI**

```
.venv/bin/python -m codebase_mcp.cli install --help
.venv/bin/python -m codebase_mcp.cli install status
.venv/bin/python -m codebase_mcp.cli install claude-code --dry-run
```

Expected: help text shows subcommands; `status` prints table; `--dry-run` prints JSON without writing.

- [ ] **Step 4: Run full test suite**

```
.venv/bin/pytest -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/codebase_mcp/cli.py
git commit -m "feat: add install CLI subgroup for dev agent MCP config"
```

---

## Task 5: `hook.py` Module

**Files:**
- Create: `src/codebase_mcp/hook.py`
- Create: `tests/test_hook.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_hook.py`:

```python
import stat
from pathlib import Path

import pytest


@pytest.fixture
def git_repo(tmp_path):
    (tmp_path / ".git" / "hooks").mkdir(parents=True)
    return tmp_path


def test_install_creates_hook(git_repo):
    from codebase_mcp.hook import MARKER, install_hook

    result = install_hook(str(git_repo))
    assert result["status"] == "installed"
    hook = git_repo / ".git" / "hooks" / "post-commit"
    assert hook.exists()
    content = hook.read_text()
    assert MARKER in content
    assert 'yacodebase-mcp update "$(git rev-parse --show-toplevel)"' in content
    assert hook.stat().st_mode & stat.S_IXUSR


def test_install_idempotent(git_repo):
    from codebase_mcp.hook import install_hook

    install_hook(str(git_repo))
    result = install_hook(str(git_repo))
    assert result["status"] == "already"


def test_install_appends_to_existing_hook(git_repo):
    from codebase_mcp.hook import MARKER, install_hook

    hook = git_repo / ".git" / "hooks" / "post-commit"
    hook.write_text("#!/bin/sh\necho hello\n")

    result = install_hook(str(git_repo))
    assert result["status"] == "appended"
    content = hook.read_text()
    assert "echo hello" in content
    assert MARKER in content


def test_install_not_git_repo(tmp_path):
    from codebase_mcp.hook import install_hook

    with pytest.raises(ValueError, match="Not a git repo"):
        install_hook(str(tmp_path))


def test_uninstall_removes_standalone_hook(git_repo):
    from codebase_mcp.hook import install_hook, uninstall_hook

    install_hook(str(git_repo))
    result = uninstall_hook(str(git_repo))
    assert result["status"] == "removed"
    assert not (git_repo / ".git" / "hooks" / "post-commit").exists()


def test_uninstall_preserves_other_hook_content(git_repo):
    from codebase_mcp.hook import MARKER, install_hook, uninstall_hook

    hook = git_repo / ".git" / "hooks" / "post-commit"
    hook.write_text("#!/bin/sh\necho hello\n")
    install_hook(str(git_repo))

    uninstall_hook(str(git_repo))
    content = hook.read_text()
    assert "echo hello" in content
    assert MARKER not in content


def test_uninstall_not_installed(git_repo):
    from codebase_mcp.hook import uninstall_hook

    result = uninstall_hook(str(git_repo))
    assert result["status"] == "not_installed"


def test_hook_status_true(git_repo):
    from codebase_mcp.hook import hook_status, install_hook

    install_hook(str(git_repo))
    assert hook_status(str(git_repo)) is True


def test_hook_status_false_no_hook(git_repo):
    from codebase_mcp.hook import hook_status

    assert hook_status(str(git_repo)) is False


def test_hook_status_false_other_hook(git_repo):
    from codebase_mcp.hook import hook_status

    hook = git_repo / ".git" / "hooks" / "post-commit"
    hook.write_text("#!/bin/sh\necho other\n")
    assert hook_status(str(git_repo)) is False
```

- [ ] **Step 2: Run to confirm failure**

```
.venv/bin/pytest tests/test_hook.py -v
```

Expected: `ERROR` — `ModuleNotFoundError: No module named 'codebase_mcp.hook'`

- [ ] **Step 3: Create `src/codebase_mcp/hook.py`**

```python
from __future__ import annotations

import stat
from pathlib import Path

MARKER = "# yacodebase-mcp auto-reindex — do not remove this line"
HOOK_CMD = 'yacodebase-mcp update "$(git rev-parse --show-toplevel)"'

_NEW_FILE_BLOCK = f"#!/bin/sh\n{MARKER}\n{HOOK_CMD}\n"
_APPEND_BLOCK = f"\n{MARKER}\n{HOOK_CMD}\n"


def _hook_path(repo: Path) -> Path:
    return repo / ".git" / "hooks" / "post-commit"


def install_hook(repo_path: str) -> dict:
    """Install post-commit hook. Returns {"status": "installed"|"appended"|"already", "path": str}."""
    abs_path = Path(repo_path).resolve()
    if not (abs_path / ".git").is_dir():
        raise ValueError(f"Not a git repo: {abs_path}")

    hook = _hook_path(abs_path)

    if hook.exists():
        content = hook.read_text()
        if MARKER in content:
            return {"status": "already", "path": str(hook)}
        hook.write_text(content.rstrip("\n") + _APPEND_BLOCK)
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return {"status": "appended", "path": str(hook)}

    hook.write_text(_NEW_FILE_BLOCK)
    hook.chmod(0o755)
    return {"status": "installed", "path": str(hook)}


def uninstall_hook(repo_path: str) -> dict:
    """Remove our block from post-commit hook. Returns {"status": "removed"|"not_installed"}."""
    abs_path = Path(repo_path).resolve()
    hook = _hook_path(abs_path)

    if not hook.exists():
        return {"status": "not_installed"}

    content = hook.read_text()
    if MARKER not in content:
        return {"status": "not_installed"}

    lines = content.splitlines()
    new_lines: list[str] = []
    i = 0
    while i < len(lines):
        if MARKER in lines[i]:
            if new_lines and new_lines[-1].strip() == "":
                new_lines.pop()
            i += 1
            if i < len(lines) and HOOK_CMD in lines[i]:
                i += 1
            continue
        new_lines.append(lines[i])
        i += 1

    remaining = "\n".join(new_lines).strip()
    if not remaining or remaining == "#!/bin/sh":
        hook.unlink()
        return {"status": "removed"}

    hook.write_text(remaining + "\n")
    return {"status": "removed"}


def hook_status(repo_path: str) -> bool:
    """Return True if our post-commit hook is installed in repo_path."""
    hook = _hook_path(Path(repo_path).resolve())
    return hook.exists() and MARKER in hook.read_text()
```

- [ ] **Step 4: Run tests**

```
.venv/bin/pytest tests/test_hook.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/codebase_mcp/hook.py tests/test_hook.py
git commit -m "feat: add hook module for post-commit auto-reindex install/uninstall"
```

---

## Task 6: `hook` CLI Group

**Files:**
- Modify: `src/codebase_mcp/cli.py`

- [ ] **Step 1: Add `hook` group to `cli.py`**

Append to the bottom of `cli.py`:

```python
@main.group()
def hook():
    """Manage post-commit git hooks for automatic reindex."""


@hook.command("install")
@click.argument("repo_path", default=".", type=click.Path(file_okay=False))
def hook_install(repo_path: str) -> None:
    """Install post-commit hook in REPO_PATH (default: current dir)."""
    from .hook import install_hook
    from .store import is_indexed

    abs_path = str(Path(repo_path).resolve())
    try:
        result = install_hook(abs_path)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1)

    status = result["status"]
    path = result["path"]
    if status == "already":
        console.print(f"[yellow]Hook already installed: {path}[/yellow]")
    elif status == "appended":
        console.print(f"[green]Hook appended to existing: {path}[/green]")
    else:
        console.print(f"[green]Hook installed: {path}[/green]")

    if not is_indexed(abs_path):
        console.print(
            f"[yellow]Note: repo not indexed yet. Run: yacodebase-mcp index {abs_path}[/yellow]"
        )


@hook.command("uninstall")
@click.argument("repo_path", default=".", type=click.Path(file_okay=False))
def hook_uninstall(repo_path: str) -> None:
    """Remove yacodebase-mcp post-commit hook from REPO_PATH."""
    from .hook import uninstall_hook

    abs_path = str(Path(repo_path).resolve())
    result = uninstall_hook(abs_path)
    if result["status"] == "not_installed":
        console.print("[yellow]Hook not installed.[/yellow]")
    else:
        console.print("[green]Hook removed.[/green]")


@hook.command("status")
@click.argument("repo_path", required=False, type=click.Path(file_okay=False))
def hook_status_cmd(repo_path: str | None) -> None:
    """Show hook status for indexed repos (or a specific REPO_PATH)."""
    from .hook import hook_status
    from .store import get_all_repos

    if repo_path:
        candidates = {str(Path(repo_path).resolve()): {"last_indexed": "—"}}
    else:
        candidates = get_all_repos()

    if not candidates:
        console.print("No repos indexed.")
        return

    table = Table(show_header=True, expand=False)
    table.add_column("Repo path", overflow="fold")
    table.add_column("Hook installed")
    table.add_column("Last indexed")

    for path, meta in candidates.items():
        installed = "[green]yes[/green]" if hook_status(path) else "[red]no[/red]"
        last = (meta.get("last_indexed") or "—")[:19]
        table.add_row(path, installed, last)

    wide_console = Console(width=10000)
    wide_console.print(table)
```

- [ ] **Step 2: Smoke-test CLI**

```
.venv/bin/python -m codebase_mcp.cli hook --help
.venv/bin/python -m codebase_mcp.cli hook status
```

Expected: help text shows `install`, `uninstall`, `status`; `status` shows indexed repos or "No repos indexed."

- [ ] **Step 3: Run full test suite**

```
.venv/bin/pytest -v
```

Expected: all PASS.

- [ ] **Step 4: Lint**

```
.venv/bin/ruff check src tests
.venv/bin/ruff format src tests
```

Fix any issues, then re-run tests.

- [ ] **Step 5: Commit**

```bash
git add src/codebase_mcp/cli.py
git commit -m "feat: add hook CLI subgroup for post-commit auto-reindex"
```

---

## Done

All features implemented. Final verification:

```
.venv/bin/pytest -v
.venv/bin/ruff check src tests
yacodebase-mcp --help
yacodebase-mcp install status
yacodebase-mcp hook status
```
