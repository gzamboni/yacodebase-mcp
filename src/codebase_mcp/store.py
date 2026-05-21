import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams


def _data_dir() -> Path:
    return Path(os.environ.get("CODEBASE_MCP_DATA_DIR", str(Path.home() / ".codebase-mcp")))


def _config_path() -> Path:
    return _data_dir() / "config.json"


def _qdrant_path() -> Path:
    return _data_dir() / "qdrant"


def get_repo_id(repo_path: str) -> str:
    return hashlib.md5(repo_path.encode()).hexdigest()[:16]


def get_client() -> QdrantClient:
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
    return repo_path in load_config()


def add_repo(repo_path: str, chunk_count: int) -> None:
    config = load_config()
    config[repo_path] = {
        "repo_id": get_repo_id(repo_path),
        "last_indexed": datetime.now(timezone.utc).isoformat(),
        "chunk_count": chunk_count,
    }
    save_config(config)


def remove_repo(repo_path: str) -> None:
    """Remove repo from config.json. Caller must delete the Qdrant collection separately."""
    config = load_config()
    config.pop(repo_path, None)
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
    """Save per-file SHA256 hashes for a repo into config.json."""
    config = load_config()
    if repo_path not in config:
        return
    config[repo_path]["file_hashes"] = hashes
    save_config(config)


def load_file_hashes(repo_path: str) -> dict[str, str]:
    """Load per-file SHA256 hashes for a repo from config.json."""
    config = load_config()
    return config.get(repo_path, {}).get("file_hashes", {})
