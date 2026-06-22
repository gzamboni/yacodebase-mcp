import json
import os
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from . import indexer
from .settings import (
    KNOWN_MODELS,
    get_settings,
    load_settings,
    patch_setting,
    save_settings,
    unset_settings_fields,
)
from .store import get_all_repos, get_client, is_indexed, load_config, remove_repo

console = Console()


@click.group()
@click.version_option(package_name="yacodebase-mcp")
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


_project_opt = click.option(
    "--project",
    is_flag=True,
    default=False,
    help="Write to .yacodebase/settings.json in current directory (project scope).",
)


@config_set.command("embedding-model")
@click.argument("model")
@click.option(
    "--vector-size",
    type=int,
    default=None,
    help="Vector dimension (required for unknown models).",
)
@_project_opt
def set_embedding_model(model: str, vector_size: int | None, project: bool) -> None:
    """Set the embedding model. Known models derive vector-size automatically."""
    if model in KNOWN_MODELS:
        resolved_size = KNOWN_MODELS[model]
    elif vector_size is not None:
        resolved_size = vector_size
    else:
        console.print(f"[red]Unknown model '{model}'. Provide vector size: --vector-size 768[/red]")
        raise SystemExit(1)
    project_path = os.getcwd() if project else None
    patch_setting("embedding_model", model, project_path=project_path)
    patch_setting("vector_size", resolved_size, project_path=project_path)
    scope = "project" if project else "global"
    console.print(f"[green]embedding_model={model}, vector_size={resolved_size} ({scope})[/green]")


@config_set.command("api-key")
@click.argument("key")
@_project_opt
def set_api_key(key: str, project: bool) -> None:
    """Set the API key for the embedding provider."""
    project_path = os.getcwd() if project else None
    if project:
        console.print("[yellow]Warning: storing api_key in project file may expose it in git.[/yellow]")
    patch_setting("api_key", key, project_path=project_path)
    scope = "project" if project else "global"
    console.print(f"[green]api_key set ({scope}).[/green]")


@config_set.command("api-base")
@click.argument("url")
@_project_opt
def set_api_base(url: str, project: bool) -> None:
    """Set the base URL for the embedding API (for OpenAI-compatible providers)."""
    project_path = os.getcwd() if project else None
    patch_setting("api_base", url, project_path=project_path)
    scope = "project" if project else "global"
    console.print(f"[green]api_base={url} ({scope})[/green]")


@config_set.command("max-chunk-chars")
@click.argument("chars", type=int)
@_project_opt
def set_max_chunk_chars(chars: int, project: bool) -> None:
    """Set max characters per chunk (default 10000). Lower if hitting token limits."""
    if chars < 1000:
        console.print("[red]Value too low (min 1000).[/red]")
        raise SystemExit(1)
    project_path = os.getcwd() if project else None
    patch_setting("max_chunk_chars", chars, project_path=project_path)
    scope = "project" if project else "global"
    console.print(f"[green]max_chunk_chars={chars} ({scope})[/green]")


@config.command("list")
@click.option(
    "--project",
    is_flag=True,
    default=False,
    help="Show effective settings for current directory (global merged with project).",
)
def config_list(project: bool) -> None:
    """Show current settings. Use --project to see effective settings for current directory."""
    repo_path = os.getcwd() if project else None
    s = load_settings(repo_path=repo_path)

    if s.api_key:
        masked_key = (s.api_key[:5] + "***") if len(s.api_key) > 5 else (s.api_key + "***")
    else:
        masked_key = "(not set)"

    scope_label = f"effective for {os.getcwd()}" if project else "global"
    table = Table(show_header=False, box=None, padding=(0, 2), title=scope_label)
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_row("embedding_model", s.embedding_model)
    table.add_row("vector_size", str(s.vector_size))
    table.add_row("api_key", masked_key)
    table.add_row("api_base", s.api_base or "(not set)")
    table.add_row("max_chunk_chars", str(s.max_chunk_chars))
    console.print(table)


@config.command("unset")
@click.argument(
    "key",
    type=click.Choice(["embedding-model", "api-key", "api-base", "max-chunk-chars"]),
)
@_project_opt
def config_unset(key: str, project: bool) -> None:
    """Remove a setting, reverting to default or env var fallback."""
    field_map = {
        "embedding-model": ["embedding_model", "vector_size"],
        "api-key": ["api_key"],
        "api-base": ["api_base"],
        "max-chunk-chars": ["max_chunk_chars"],
    }
    project_path = os.getcwd() if project else None
    unset_settings_fields(field_map[key], project_path=project_path)
    scope = "project" if project else "global"
    console.print(f"[green]{key} unset ({scope}).[/green]")


@main.group()
def install():
    """Install MCP server config in dev agent global settings."""


def _do_install(agent_name: str, dry_run: bool) -> None:
    from .agents import AGENTS

    agent = AGENTS[agent_name]
    path = str(agent.config_path())
    try:
        data = agent.read_config()
    except (json.JSONDecodeError, OSError) as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1)

    if agent.is_installed(data):
        console.print(f"[yellow]Already configured: {path}[/yellow]")
        return

    new_data = agent.merge(data)
    if dry_run:
        console.print(f"[bold]Would write to {path}:[/bold]")
        console.print(json.dumps(new_data, indent=2), markup=False, highlight=False)
        return

    try:
        agent.write_config(new_data)
    except OSError as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1)
    console.print(f"[green]Installed: {path}[/green]")


@install.command("claude-code")
@click.option("--dry-run", is_flag=True, help="Print changes without writing.")
def install_claude_code(dry_run: bool) -> None:
    """Install MCP config for Claude Code."""
    _do_install("claude-code", dry_run)


@install.command("cursor")
@click.option("--dry-run", is_flag=True, help="Print changes without writing.")
def install_cursor(dry_run: bool) -> None:
    """Install MCP config for Cursor."""
    _do_install("cursor", dry_run)


@install.command("windsurf")
@click.option("--dry-run", is_flag=True, help="Print changes without writing.")
def install_windsurf(dry_run: bool) -> None:
    """Install MCP config for Windsurf."""
    _do_install("windsurf", dry_run)


@install.command("copilot")
@click.option("--dry-run", is_flag=True, help="Print changes without writing.")
def install_copilot(dry_run: bool) -> None:
    """Install MCP config for GitHub Copilot (VS Code)."""
    _do_install("copilot", dry_run)


@install.command("zed")
@click.option("--dry-run", is_flag=True, help="Print changes without writing.")
def install_zed(dry_run: bool) -> None:
    """Install MCP config for Zed."""
    _do_install("zed", dry_run)


@install.command("opencode")
@click.option("--dry-run", is_flag=True, help="Print changes without writing.")
def install_opencode(dry_run: bool) -> None:
    """Install MCP config for OpenCode."""
    _do_install("opencode", dry_run)


@install.command("codex")
@click.option("--dry-run", is_flag=True, help="Print changes without writing.")
def install_codex(dry_run: bool) -> None:
    """Install MCP config for OpenAI Codex CLI (~/.codex/config.toml)."""
    _do_install("codex", dry_run)


@install.command("all")
@click.option("--dry-run", is_flag=True, help="Print changes without writing.")
def install_all(dry_run: bool) -> None:
    """Install MCP config in all supported dev agents."""
    from .agents import AGENTS, install_agent

    for name, agent in AGENTS.items():
        try:
            status = install_agent(agent, dry_run=dry_run)
        except (json.JSONDecodeError, OSError) as e:
            console.print(f"[red]{name}: error — {e}[/red]")
            continue
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
        try:
            flag = agent.is_installed()
            installed = "[green]yes[/green]" if flag else "[red]no[/red]"
        except (json.JSONDecodeError, OSError):
            installed = "[yellow]parse error[/yellow]"
        table.add_row(agent.label, str(agent.config_path()), installed)

    wide_console = Console(width=10000)
    wide_console.print(table)


@main.group()
def inject():
    """Inject/eject agent instruction files so agents always use codebase-search."""


@inject.command("run")
@click.argument("repo_path", default=".", type=click.Path(exists=True, file_okay=False))
@click.option("--agent", "agents", multiple=True, help="Target agent(s). Repeatable. Default: all.")
@click.option("--dry-run", is_flag=True, help="Print changes without writing.")
def inject_run(repo_path: str, agents: tuple[str, ...], dry_run: bool) -> None:
    """Inject codebase-search instructions into agent rule files in REPO_PATH."""
    from .agents import INJECT_TARGETS

    repo = Path(repo_path).resolve()
    targets = {k: v for k, v in INJECT_TARGETS.items() if k in agents} if agents else INJECT_TARGETS
    for name, target in targets.items():
        status = target.inject(repo, dry_run=dry_run)
        p = str(target.instructions_path(repo))
        if status == "already":
            console.print(f"[yellow]{name}: already injected ({p})[/yellow]")
        elif status == "dry_run":
            console.print(f"[cyan]{name}: would write to {p}[/cyan]")
        else:
            console.print(f"[green]{name}: injected ({p})[/green]")


@inject.command("eject")
@click.argument("repo_path", default=".", type=click.Path(exists=True, file_okay=False))
@click.option("--agent", "agents", multiple=True, help="Target agent(s). Repeatable. Default: all.")
@click.option("--dry-run", is_flag=True, help="Print changes without writing.")
def inject_eject(repo_path: str, agents: tuple[str, ...], dry_run: bool) -> None:
    """Remove injected codebase-search instructions from agent rule files in REPO_PATH."""
    from .agents import INJECT_TARGETS

    repo = Path(repo_path).resolve()
    targets = {k: v for k, v in INJECT_TARGETS.items() if k in agents} if agents else INJECT_TARGETS
    for name, target in targets.items():
        status = target.eject(repo, dry_run=dry_run)
        p = str(target.instructions_path(repo))
        if status == "not_found":
            console.print(f"[dim]{name}: not injected[/dim]")
        elif status == "dry_run":
            console.print(f"[cyan]{name}: would remove from {p}[/cyan]")
        else:
            console.print(f"[green]{name}: ejected ({p})[/green]")


@inject.command("status")
@click.argument("repo_path", default=".", type=click.Path(exists=True, file_okay=False))
def inject_status(repo_path: str) -> None:
    """Show injection status for all agents in REPO_PATH."""
    from .agents import INJECT_TARGETS

    repo = Path(repo_path).resolve()
    table = Table(title=f"Inject status — {repo}")
    table.add_column("Agent")
    table.add_column("File")
    table.add_column("Injected")
    for name, target in INJECT_TARGETS.items():
        injected = "[green]yes[/green]" if target.is_injected(repo) else "[red]no[/red]"
        table.add_row(target.label, str(target.instructions_path(repo)), injected)
    console.print(table)


@main.group()
def hook():
    """Manage post-commit git hooks for automatic reindex."""


@hook.command("install")
@click.argument("repo_path", default=".", type=click.Path(exists=True, file_okay=False))
def hook_install(repo_path: str) -> None:
    """Install post-commit hook in REPO_PATH (default: current dir)."""
    from .hook import install_hook

    abs_path = str(Path(repo_path).resolve())
    try:
        result = install_hook(abs_path)
    except (ValueError, OSError) as e:
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
@click.argument("repo_path", default=".", type=click.Path(exists=True, file_okay=False))
def hook_uninstall(repo_path: str) -> None:
    """Remove yacodebase-mcp post-commit hook from REPO_PATH."""
    from .hook import uninstall_hook

    abs_path = str(Path(repo_path).resolve())
    try:
        result = uninstall_hook(abs_path)
    except (ValueError, OSError) as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1)
    if result["status"] == "not_installed":
        console.print("[yellow]Hook not installed.[/yellow]")
    else:
        console.print("[green]Hook removed.[/green]")


@hook.command("status")
@click.argument("repo_path", required=False, type=click.Path(file_okay=False))
def hook_status_cmd(repo_path: str | None) -> None:
    """Show hook status for indexed repos (or a specific REPO_PATH)."""
    from .hook import hook_status

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
    table.add_column("Last Indexed")

    for path, meta in candidates.items():
        installed = "[green]yes[/green]" if hook_status(path) else "[red]no[/red]"
        last = (meta.get("last_indexed") or "—")[:19]
        table.add_row(path, installed, last)

    wide_console = Console(width=10000)
    wide_console.print(table)


@main.command("completion")
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]))
def completion(shell: str) -> None:
    """Print shell completion script. Source it to enable tab completion.

    \b
    bash:  source <(yacodebase-mcp completion bash)
    zsh:   source <(yacodebase-mcp completion zsh)
    fish:  yacodebase-mcp completion fish | source
    """
    from click.shell_completion import BashComplete, FishComplete, ZshComplete

    if shell == "fish":
        # Click 8.4 changed format_completion to emit type\nvalue\nhelp (one field
        # per line). Fish splits command output on newlines when capturing into a
        # variable, so the for-loop template gets individual fields, not triplets.
        # Emit a corrected script that reads $response in groups of three instead.
        click.echo(
            """\
function _yacodebase_mcp_completion;
    set -l response (env _YACODEBASE_MCP_COMPLETE=fish_complete COMP_WORDS=(commandline -cp) COMP_CWORD=(commandline -t) yacodebase-mcp);
    set -l n (count $response);
    set -l i 1;
    while test $i -le $n;
        set -l type $response[$i];
        set -l value $response[(math $i + 1)];
        set -l help $response[(math $i + 2)];
        set i (math $i + 3);
        if test $type = "dir";
            __fish_complete_directories $value;
        else if test $type = "file";
            __fish_complete_path $value;
        else if test $type = "plain";
            if test $help != "_";
                echo $value\\t$help;
            else;
                echo $value;
            end;
        end;
    end;
end;

complete --no-files --command yacodebase-mcp --arguments "(_yacodebase_mcp_completion)";
"""
        )
        return
    cls = {"bash": BashComplete, "zsh": ZshComplete}[shell]
    ctx = main.make_context("yacodebase-mcp", [], resilient_parsing=True)
    comp = cls(main, ctx, "yacodebase-mcp", "_YACODEBASE_MCP_COMPLETE")
    click.echo(comp.source(), nl=False)
