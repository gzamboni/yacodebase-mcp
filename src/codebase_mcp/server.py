from pathlib import Path

from fastmcp import FastMCP

from . import searcher
from .ast_chunker import chunk_file_ast
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
