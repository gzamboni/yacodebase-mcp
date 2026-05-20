from fastmcp import FastMCP

from . import searcher
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
