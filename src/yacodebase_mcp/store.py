import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams


def _data_dir() -> Path:
    override = os.environ.get("YACODEBASE_MCP_DATA_DIR") or os.environ.get("CODEBASE_MCP_DATA_DIR")
    if override:
        return Path(override)
    old = Path.home() / ".codebase-mcp"
    new = Path.home() / ".yacodebase-mcp"
    if old.exists() and not new.exists():
        try:
            old.rename(new)
        except OSError:
            import shutil
            import warnings

            try:
                shutil.move(str(old), str(new))
            except OSError as move_err:
                warnings.warn(f"Could not migrate data dir {old} → {new}: {move_err}", stacklevel=2)
    return new


def _config_path() -> Path:
    return _data_dir() / "config.json"


def _qdrant_path() -> Path:
    return _data_dir() / "qdrant"


def get_repo_id(repo_path: str) -> str:
    return hashlib.md5(repo_path.encode()).hexdigest()[:16]


def get_current_branch(repo_path: str) -> str | None:
    """Return current git branch name for repo_path, or None if not a git repo/detached HEAD."""
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "symbolic-ref", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return branch or None


def repo_key(repo_path: str) -> str:
    """Config/collection key for repo_path — branch-qualified when inside a git repo."""
    branch = get_current_branch(repo_path)
    return f"{repo_path}#{branch}" if branch else repo_path


def select_repo_entry(config: dict, repo_path: str) -> tuple[str, dict] | None:
    """Look up repo_path's entry in an already-loaded config dict, falling back
    to a legacy bare-path key. Pure — does no I/O or migration; use find_repo_entry
    for the persisting lookup."""
    key = repo_key(repo_path)
    if key in config:
        return key, config[key]
    if repo_path in config and repo_path != key:
        return repo_path, config[repo_path]
    return None


def find_repo_entry(repo_path: str) -> tuple[str, dict] | None:
    """Look up repo_path's config entry, migrating a legacy pre-branch-aware
    entry (keyed by the bare path) onto the branch-qualified key in place.

    Without this, upgrading orphans every already-indexed git repo: repo_key()
    now returns a different string than what the entry was stored under, so
    the old collection/metadata becomes silently unreachable. Migrating keeps
    the existing repo_id (and thus the existing Qdrant collection) intact.
    """
    config = load_config()
    found = select_repo_entry(config, repo_path)
    if not found:
        return None
    key, entry = found
    canonical_key = repo_key(repo_path)
    if key != canonical_key:
        config[canonical_key] = config.pop(key)
        save_config(config)
        key = canonical_key
    return key, entry


def resolve_repo_id(repo_path: str) -> str:
    """Return the Qdrant collection id to use for repo_path (current branch),
    reusing an existing (possibly just-migrated) entry's id if present."""
    entry = find_repo_entry(repo_path)
    return entry[1]["repo_id"] if entry else get_repo_id(repo_key(repo_path))


def get_client(repo_path: str | None = None) -> QdrantClient:
    from .settings import load_settings

    settings = load_settings(repo_path)
    if settings.qdrant_url:
        # ponytail: default client timeout (5s) is too short for batch upserts over a
        # network link; bump to 60s rather than adding a config knob nobody's asked for.
        return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=60)
    _qdrant_path().mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=str(_qdrant_path()))


def load_config() -> dict:
    path = _config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def save_config(config: dict) -> None:
    _data_dir().mkdir(parents=True, exist_ok=True)
    _config_path().write_text(json.dumps(config, indent=2))


def is_indexed(repo_path: str) -> bool:
    return find_repo_entry(repo_path) is not None


def add_repo(repo_path: str, chunk_count: int) -> None:
    config = load_config()
    branch = get_current_branch(repo_path)
    key = f"{repo_path}#{branch}" if branch else repo_path
    if key not in config and repo_path in config and repo_path != key:
        config[key] = config.pop(repo_path)
    repo_id = config.get(key, {}).get("repo_id") or get_repo_id(key)
    config[key] = {
        "repo_id": repo_id,
        "path": repo_path,
        "branch": branch,
        "last_indexed": datetime.now(timezone.utc).isoformat(),
        "chunk_count": chunk_count,
    }
    save_config(config)


def remove_repo(repo_path: str) -> None:
    """Remove repo (current branch). Caller must delete the Qdrant collection separately."""
    entry = find_repo_entry(repo_path)
    if not entry:
        return
    config = load_config()
    config.pop(entry[0], None)
    save_config(config)


def get_all_repos() -> dict:
    return load_config()


def ensure_collection(client: QdrantClient, repo_id: str, vector_size: int) -> None:
    if client.collection_exists(collection_name=repo_id):
        client.delete_collection(collection_name=repo_id)
    client.create_collection(
        collection_name=repo_id,
        vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
    )


def save_file_hashes(repo_path: str, hashes: dict[str, str]) -> None:
    """Save per-file SHA256 hashes for a repo (current branch) into config.json."""
    entry = find_repo_entry(repo_path)
    if not entry:
        return
    key, _ = entry
    config = load_config()
    config[key]["file_hashes"] = hashes
    save_config(config)


def load_file_hashes(repo_path: str) -> dict[str, str]:
    """Load per-file SHA256 hashes for a repo (current branch) from config.json."""
    entry = find_repo_entry(repo_path)
    return entry[1].get("file_hashes", {}) if entry else {}
