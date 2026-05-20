from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from . import indexer
from .store import get_all_repos, get_client, is_indexed, load_config, remove_repo

console = Console()


@click.group()
def main():
    """Codebase vector search — index repos, search via MCP."""


@main.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False))
def index(path: str) -> None:
    """Index a repo. Fails if already indexed — use reindex to update."""
    abs_path = str(Path(path).resolve())
    if is_indexed(abs_path):
        console.print("[red]Already indexed. Use `reindex` to update.[/red]")
        raise SystemExit(1)
    with console.status(f"Indexing {abs_path}..."):
        count = indexer.index_repo(abs_path)
    console.print(f"[green]Indexed {count} chunks from {abs_path}[/green]")


@main.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False))
def reindex(path: str) -> None:
    """Re-index a repo, replacing any existing index."""
    abs_path = str(Path(path).resolve())
    with console.status(f"Re-indexing {abs_path}..."):
        count = indexer.index_repo(abs_path)
    console.print(f"[green]Re-indexed {count} chunks from {abs_path}[/green]")


@main.command("list")
def list_repos() -> None:
    """List all indexed repos with stats."""
    repos = get_all_repos()
    if not repos:
        console.print("No repos indexed.")
        return
    table = Table(show_header=True, expand=False)
    table.add_column("Path", no_wrap=True, overflow="fold")
    table.add_column("Chunks")
    table.add_column("Last Indexed")
    for path, meta in repos.items():
        table.add_row(path, str(meta["chunk_count"]), meta["last_indexed"])
    wide_console = Console(width=10000)
    wide_console.print(table)


@main.command()
@click.argument("path")
def remove(path: str) -> None:
    """Remove a repo from the index."""
    abs_path = str(Path(path).resolve())
    config = load_config()
    if abs_path not in config:
        console.print(f"[red]Not indexed: {abs_path}[/red]")
        raise SystemExit(1)
    repo_id = config[abs_path]["repo_id"]
    client = get_client()
    if client.collection_exists(repo_id):
        client.delete_collection(repo_id)
    remove_repo(abs_path)
    console.print(f"[green]Removed {abs_path}[/green]")


@main.command()
def serve() -> None:
    """Start the MCP server (used by Claude Code)."""
    from .server import mcp
    mcp.run(transport="stdio")
