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
    """Install post-commit hook.

    Returns {"status": "installed"|"appended"|"already", "path": str}.
    """
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
    """Remove our block from post-commit hook.

    Returns {"status": "removed"|"not_installed"}.
    """
    abs_path = Path(repo_path).resolve()
    if not (abs_path / ".git").is_dir():
        raise ValueError(f"Not a git repo: {abs_path}")
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
            # skip blank lines between marker and command (tolerates hand-edited files)
            while i < len(lines) and lines[i].strip() == "":
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
