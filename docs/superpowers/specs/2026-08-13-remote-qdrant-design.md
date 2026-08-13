# Remote Qdrant support — design

## Problem

`store.get_client()` hardcodes `QdrantClient(path=str(_qdrant_path()))` — always
local on-disk Qdrant. No way to point yacodebase-mcp at a remote Qdrant server
(self-hosted or Qdrant Cloud).

## Approach

Add two optional settings fields, following the existing `api_key`/`api_base`
pattern in `settings.py`:

- `qdrant_url: str | None` — e.g. `http://qdrant.internal:6333` or a Qdrant
  Cloud URL. When set, `get_client()` connects remotely instead of local disk.
- `qdrant_api_key: str | None` — passed to `QdrantClient(api_key=...)` when
  present. Optional (self-hosted may run without auth).

`store.get_client()` gains an optional `repo_path` param (mirrors
`load_settings(repo_path=...)`), loads settings, and branches:

```python
def get_client(repo_path: str | None = None) -> QdrantClient:
    s = load_settings(repo_path)
    if s.qdrant_url:
        return QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key)
    return QdrantClient(path=str(_qdrant_path()))
```

Callers of `get_client()` (indexer, searcher, cli) pass through `repo_path`
where they already have it, so project-level settings can override global.

## CLI

Mirror `config set api-key` / `config set api-base`:

- `yacodebase-mcp config set qdrant-url URL [--project]`
- `yacodebase-mcp config set qdrant-api-key KEY [--project]`
- `config list` shows `qdrant_url` and masked `qdrant_api_key`
- `config unset qdrant-url` / `config unset qdrant-api-key`

## Non-goals

- No data migration between local and remote Qdrant. Switching servers means
  starting with an empty collection on the new server; existing repos need
  re-indexing there. This is a manual, deliberate action by the user — no
  automatic sync.
- No connection health check beyond what `qdrant-client` already raises on
  first use.

## Testing

- `tests/test_store.py`: `get_client` returns remote client when
  `qdrant_url` set (mock `QdrantClient` constructor call args), local path
  client otherwise.
- `tests/test_settings.py`: round-trip `qdrant_url`/`qdrant_api_key` through
  `save_settings`/`load_settings`/`patch_setting`/`unset_settings_fields`.
- `tests/test_cli.py`: new `config set qdrant-url` / `qdrant-api-key`
  commands write expected settings; `config list` masks the key.
