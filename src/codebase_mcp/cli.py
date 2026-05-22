from pathlib import Path

import click
import json
from rich.console import Console
from rich.table import Table

from . import indexer
from .settings import KNOWN_MODELS, get_settings, save_settings, unset_settings_fields
from .store import get_all_repos, get_client, is_indexed, load_config, remove_repo

console = Console()


@click.group()
def main():
    """Codebase vector search — index repos, search via MCP."""
    import sys
    if Path(sys.argv[0]).stem == "codebase-mcp":
        click.echo("Warning: codebase-mcp is deprecated, use yacodebase-mcp", err=True)


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


@main.command()
@click.argument("repo_path", type=click.Path(exists=True, file_okay=False))
def update(repo_path):
    """Incrementally update index for REPO_PATH (only re-indexes changed files)."""
    from .indexer import index_repo_incremental

    abs_path = str(Path(repo_path).resolve())
    if not is_indexed(abs_path):
        click.echo(f"Not indexed. Run: yacodebase-mcp index {repo_path}", err=True)
        raise SystemExit(1)
    count = index_repo_incremental(abs_path)
    if count == 0:
        click.echo("No changes detected. Index is up to date.")
    else:
        click.echo(f"Updated {count} chunks.")


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


@main.group()
def config():
    """Manage global settings (embedding model, API key, API host)."""


@config.group("set")
def config_set():
    """Set a config value."""


@config_set.command("embedding-model")
@click.argument("model")
@click.option(
    "--vector-size",
    type=int,
    default=None,
    help="Vector dimension (required for unknown models).",
)
def set_embedding_model(model: str, vector_size: int | None) -> None:
    """Set the embedding model. Known models derive vector-size automatically."""
    if model in KNOWN_MODELS:
        resolved_size = KNOWN_MODELS[model]
    elif vector_size is not None:
        resolved_size = vector_size
    else:
        console.print(f"[red]Unknown model '{model}'. Provide vector size: --vector-size 768[/red]")
        raise SystemExit(1)
    s = get_settings()
    s.embedding_model = model
    s.vector_size = resolved_size
    save_settings(s)
    console.print(f"[green]embedding_model={model}, vector_size={resolved_size}[/green]")


@config_set.command("api-key")
@click.argument("key")
def set_api_key(key: str) -> None:
    """Set the API key for the embedding provider."""
    s = get_settings()
    s.api_key = key
    save_settings(s)
    console.print("[green]api_key set.[/green]")


@config_set.command("api-base")
@click.argument("url")
def set_api_base(url: str) -> None:
    """Set the base URL for the embedding API (for OpenAI-compatible providers)."""
    s = get_settings()
    s.api_base = url
    save_settings(s)
    console.print(f"[green]api_base={url}[/green]")


@config.command("list")
def config_list() -> None:
    """Show current global settings."""
    s = get_settings()

    if s.api_key:
        masked_key = (s.api_key[:5] + "***") if len(s.api_key) > 5 else (s.api_key + "***")
    else:
        masked_key = "(not set)"

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_row("embedding_model", s.embedding_model)
    table.add_row("vector_size", str(s.vector_size))
    table.add_row("api_key", masked_key)
    table.add_row("api_base", s.api_base or "(not set)")
    console.print(table)


@config.command("unset")
@click.argument("key", type=click.Choice(["embedding-model", "api-key", "api-base"]))
def config_unset(key: str) -> None:
    """Remove a setting, reverting to default or env var fallback."""
    field_map = {
        "embedding-model": ["embedding_model", "vector_size"],
        "api-key": ["api_key"],
        "api-base": ["api_base"],
    }
    unset_settings_fields(field_map[key])
    console.print(f"[green]{key} unset.[/green]")


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
