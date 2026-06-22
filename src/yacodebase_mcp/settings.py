import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .store import _data_dir

KNOWN_MODELS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}

_FIELDS = {"embedding_model", "vector_size", "api_key", "api_base", "max_chunk_chars"}
_OPTIONAL_FIELDS = {"api_key", "api_base"}

DEFAULT_MAX_CHUNK_CHARS = 10_000


@dataclass
class Settings:
    embedding_model: str = "text-embedding-3-small"
    vector_size: int = 1536
    api_key: str | None = None
    api_base: str | None = None
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS


def _settings_path() -> Path:
    return _data_dir() / "settings.json"


def _project_settings_path(repo_path: str) -> Path:
    return Path(repo_path) / ".yacodebase" / "settings.json"


def _load_raw(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
        return {k: v for k, v in data.items() if k in _FIELDS}
    except (OSError, json.JSONDecodeError):
        return {}


def load_settings(repo_path: str | None = None) -> Settings:
    data = _load_raw(_settings_path())
    if repo_path:
        project_data = _load_raw(_project_settings_path(repo_path))
        data = {**data, **project_data}
    return Settings(**data) if data else Settings()


def save_settings(s: Settings, project_path: str | None = None) -> None:
    if project_path:
        path = _project_settings_path(project_path)
    else:
        path = _settings_path()
        _data_dir().mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {k: v for k, v in asdict(s).items() if k not in _OPTIONAL_FIELDS or v is not None}
    path.write_text(json.dumps(data, indent=2))


def patch_setting(key: str, value, project_path: str | None = None) -> None:
    """Set a single field without touching other fields in the settings file."""
    if project_path:
        path = _project_settings_path(project_path)
    else:
        path = _settings_path()
        _data_dir().mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _load_raw(path)
    if value is None:
        data.pop(key, None)
    else:
        data[key] = value
    path.write_text(json.dumps(data, indent=2))


def get_settings(repo_path: str | None = None) -> Settings:
    return load_settings(repo_path)


def unset_settings_fields(keys: list[str], project_path: str | None = None) -> None:
    if project_path:
        path = _project_settings_path(project_path)
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        path = _settings_path()
        _data_dir().mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        data = {}
    for k in keys:
        data.pop(k, None)
    data = {k: v for k, v in data.items() if v is not None}
    path.write_text(json.dumps(data, indent=2))
