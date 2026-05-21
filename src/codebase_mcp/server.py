import re
from datetime import datetime, timezone
from pathlib import Path

from fastmcp import FastMCP
from qdrant_client.models import FieldCondition, Filter, MatchText

from . import searcher
from .ast_chunker import chunk_file_ast
from .knowledge import add_decision as _add_decision
from .knowledge import add_note as _add_note
from .knowledge import get_notes as _get_notes
from .knowledge import search_decisions as _search_decisions
from .knowledge import update_decision as _update_decision
from .store import get_all_repos

mcp = FastMCP("codebase-search")


@mcp.tool()
def search_codebase(query: str, repo_path: str | None = None) -> str:
    """Search indexed codebase for relevant code and docs.

    Args:
        query: Natural language description of what to find.
        repo_path: Absolute path to a specific repo. Omit to search all indexed repos.
    """
    return searcher.search(query, repo_path)


@mcp.tool()
def list_indexed_repos() -> str:
    """List all indexed repositories with chunk count and last indexed time."""
    repos = get_all_repos()
    if not repos:
        return "No repos indexed. Run: codebase-mcp index /path/to/repo"
    lines = [
        f"- {path}  ({meta['chunk_count']} chunks, indexed {meta['last_indexed']})"
        for path, meta in repos.items()
    ]
    return "\n".join(lines)


@mcp.tool()
def search_symbols(name: str, repo_path: str | None = None) -> str:
    """Search for functions, methods, or classes by name across indexed repos.

    Args:
        name: Symbol name or substring to search (case-insensitive).
        repo_path: Absolute path to a specific repo. Omit to search all.
    """
    from .store import get_client

    config = get_all_repos()
    if not config:
        return "No repos indexed. Run: codebase-mcp index /path/to/repo"

    if repo_path:
        abs_path = str(Path(repo_path).resolve())
        candidates = {abs_path: config[abs_path]} if abs_path in config else {}
    else:
        candidates = config

    if not candidates:
        return f"Repo not indexed: {repo_path}"

    qdrant = get_client()
    results = []

    for path, meta in candidates.items():
        repo_id = meta["repo_id"]
        try:
            points, _ = qdrant.scroll(
                collection_name=repo_id,
                scroll_filter=Filter(
                    must=[FieldCondition(key="symbol_name", match=MatchText(text=name))]
                ),
                limit=50,
                with_payload=True,
                with_vectors=False,
            )
        except Exception:
            continue
        for p in points:
            pay = p.payload
            sym = pay.get("symbol_name") or ""
            if sym and name.lower() in sym.lower():
                results.append(
                    f"  {pay.get('node_type', '?')}  {sym}"
                    f"  {pay['file']}:{pay['start_line']}-{pay['end_line']}"
                )

    if not results:
        return f"No symbols matching '{name}' found."
    return f"Symbols matching '{name}':\n" + "\n".join(results)


_TODO_PATTERN = re.compile(r"#\s*(TODO|FIXME|HACK|BUG|NOTE|XXX)\b[:\s]*(.*)", re.IGNORECASE)


@mcp.tool()
def find_todos(repo_path: str | None = None) -> str:
    """Find TODO, FIXME, HACK, BUG, NOTE comments in indexed repos.

    Args:
        repo_path: Absolute path to a specific repo. Omit to search all indexed repos.
    """
    from .indexer import iter_files

    config = get_all_repos()
    if not config:
        return "No repos indexed. Run: codebase-mcp index /path/to/repo"

    if repo_path:
        abs_path = str(Path(repo_path).resolve())
        candidates = {abs_path: config[abs_path]} if abs_path in config else {}
    else:
        candidates = config

    if not candidates:
        return f"Repo not indexed: {repo_path}"

    found: list[str] = []
    for path in candidates:
        for filepath in iter_files(Path(path)):
            try:
                text = filepath.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                m = _TODO_PATTERN.search(line)
                if m:
                    rel = str(filepath.relative_to(path))
                    found.append(f"  [{m.group(1).upper()}] {rel}:{lineno}  {m.group(2).strip()}")

    if not found:
        return "No TODO/FIXME/HACK/BUG/NOTE comments found."
    return f"Found {len(found)} items:\n" + "\n".join(found)


@mcp.tool()
def get_file_outline(file_path: str) -> str:
    """Return the structural outline (functions, methods, classes) of a source file.

    Args:
        file_path: Absolute path to the source file.
    """
    path = Path(file_path)
    if not path.exists():
        return f"File not found: {file_path}"
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return f"Cannot read file: {e}"

    chunks = chunk_file_ast(content, path.name, str(path.parent))
    if not chunks:
        return (
            f"No AST outline available for {path.name}"
            " (unsupported language or no top-level symbols found)"
        )

    lines = [f"## {path.name}"]
    for c in chunks:
        name = c.get("symbol_name") or "<anonymous>"
        lines.append(f"  {c['node_type']}  {name}  (lines {c['start_line']}–{c['end_line']})")
    return "\n".join(lines)


@mcp.tool()
def what_changed(repo_path: str | None = None) -> str:
    """Show files added or modified since the last index run.

    Args:
        repo_path: Absolute path to a specific repo. Omit to check all indexed repos.
    """
    from .indexer import iter_files

    config = get_all_repos()
    if not config:
        return "No repos indexed. Run: codebase-mcp index /path/to/repo"

    if repo_path:
        abs_path = str(Path(repo_path).resolve())
        candidates = {abs_path: config[abs_path]} if abs_path in config else {}
    else:
        candidates = config

    if not candidates:
        return f"Repo not indexed: {repo_path}"

    parts: list[str] = []
    for path, meta in candidates.items():
        last_indexed = datetime.fromisoformat(meta["last_indexed"])
        if last_indexed.tzinfo is None:
            last_indexed = last_indexed.replace(tzinfo=timezone.utc)

        changed: list[str] = []
        for filepath in iter_files(Path(path)):
            mtime = datetime.fromtimestamp(filepath.stat().st_mtime, tz=timezone.utc)
            if mtime > last_indexed:
                rel = str(filepath.relative_to(path))
                changed.append(f"  modified  {rel}")

        if changed:
            parts.append(
                f"{path} ({len(changed)} changed since {meta['last_indexed'][:19]}):\n"
                + "\n".join(changed)
            )
        else:
            parts.append(f"{path}: no changes since {meta['last_indexed'][:19]}")

    return "\n\n".join(parts)


@mcp.tool()
def add_decision(title: str, body: str, category: str = "general") -> str:
    """Record an architectural decision for future sessions.

    Args:
        title: Short title for the decision.
        body: Detailed explanation and rationale.
        category: Category label (e.g. 'architecture', 'security', 'performance').
    """
    decision_id = _add_decision(title, body, category)
    return f"Decision #{decision_id} saved: {title}"


@mcp.tool()
def search_decisions(query: str = "", category: str = "") -> str:
    """Search recorded architectural decisions.

    Args:
        query: Keyword to search in title and body. Omit to list all.
        category: Filter by category. Omit to search all categories.
    """
    results = _search_decisions(query=query, category=category)
    if not results:
        return "No decisions found."
    lines = []
    for d in results:
        lines.append(
            f"[#{d['id']}] [{d['status']}] {d['title']} ({d['category']})\n  {d['body'][:120]}"
        )
    return "\n\n".join(lines)


@mcp.tool()
def update_decision(decision_id: int, status: str) -> str:
    """Update the status of an architectural decision.

    Args:
        decision_id: The ID from search_decisions output.
        status: New status: 'active', 'superseded', 'implemented', or 'rejected'.
    """
    valid = {"active", "superseded", "implemented", "rejected"}
    if status not in valid:
        return f"Invalid status '{status}'. Use: {', '.join(sorted(valid))}"
    updated = _update_decision(decision_id, status)
    if not updated:
        return f"Decision #{decision_id} not found."
    return f"Decision #{decision_id} status updated to '{status}'"


@mcp.tool()
def add_note(content: str, scope: str = "project", reference: str | None = None) -> str:
    """Save a note that persists across sessions.

    Args:
        content: The note text.
        scope: 'project', 'file', or 'symbol'.
        reference: File path or symbol name the note refers to (optional).
    """
    note_id = _add_note(content, scope, reference)
    return f"Note #{note_id} saved."


@mcp.tool()
def get_notes(scope: str = "") -> str:
    """Retrieve saved notes.

    Args:
        scope: Filter by scope ('project', 'file', 'symbol'). Omit for all.
    """
    notes = _get_notes(scope=scope)
    if not notes:
        return "No notes found."
    lines = []
    for n in notes:
        ref = f" [{n['reference']}]" if n.get("reference") else ""
        lines.append(f"[#{n['id']}] [{n['scope']}]{ref} {n['content']}")
    return "\n".join(lines)


@mcp.tool()
def session_bootstrap(repo_path: str | None = None) -> str:
    """Orient the agent for a new session: repo status, recent changes, active decisions, notes.

    Call this at the start of every session instead of reading files for orientation.

    Args:
        repo_path: Absolute path to a specific repo. Omit to summarize all indexed repos.
    """
    from .indexer import iter_files

    sections: list[str] = ["# Session Bootstrap\n"]

    config = get_all_repos()
    if not config:
        return "No repos indexed. Run: codebase-mcp index /path/to/repo"

    if repo_path:
        abs_path = str(Path(repo_path).resolve())
        candidates = {abs_path: config[abs_path]} if abs_path in config else {}
    else:
        candidates = config

    if not candidates:
        return f"Repo not indexed: {repo_path}"

    repo_lines = ["## Indexed Repos"]
    for path, meta in candidates.items():
        repo_lines.append(
            f"  {path}  —  {meta['chunk_count']} chunks, last indexed {meta['last_indexed'][:19]}"
        )
    sections.append("\n".join(repo_lines))

    changed_parts: list[str] = []
    for path, meta in candidates.items():
        last_indexed = datetime.fromisoformat(meta["last_indexed"])
        if last_indexed.tzinfo is None:
            last_indexed = last_indexed.replace(tzinfo=timezone.utc)
        changed = []
        for filepath in iter_files(Path(path)):
            mtime = datetime.fromtimestamp(filepath.stat().st_mtime, tz=timezone.utc)
            if mtime > last_indexed:
                changed.append(str(filepath.relative_to(path)))
        if changed:
            changed_parts.append(f"{path}: {len(changed)} file(s) changed since last index")
    sections.append(
        "## Changes Since Last Index\n"
        + ("\n".join(f"  {c}" for c in changed_parts) if changed_parts else "  None detected")
    )

    decisions = _search_decisions()
    active = [d for d in decisions if d["status"] == "active"]
    if active:
        dec_lines = ["## Active Decisions"]
        for d in active[:10]:
            dec_lines.append(f"  [#{d['id']}] {d['title']} ({d['category']})")
        sections.append("\n".join(dec_lines))

    notes = _get_notes()
    if notes:
        note_lines = ["## Notes"]
        for n in notes[:5]:
            ref = f" [{n['reference']}]" if n.get("reference") else ""
            note_lines.append(f"  [#{n['id']}]{ref} {n['content'][:80]}")
        sections.append("\n".join(note_lines))

    return "\n\n".join(sections)
