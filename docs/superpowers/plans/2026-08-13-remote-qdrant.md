# Remote Qdrant Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let yacodebase-mcp connect to a remote Qdrant server (self-hosted or Qdrant Cloud) instead of the always-local on-disk instance.

**Architecture:** Add `qdrant_url` / `qdrant_api_key` to the existing `Settings` dataclass (same optional-field pattern as `api_key`/`api_base`). `store.get_client(repo_path=None)` loads settings and, when `qdrant_url` is set, returns `QdrantClient(url=..., api_key=...)`; otherwise falls back to the current local-path client. CLI gets two new `config set`/`unset` subcommands mirroring `api-key`/`api-base`.

**Tech Stack:** Python, `qdrant-client`, Click (CLI), pytest.

## Global Constraints

- Follow existing `_FIELDS`/`_OPTIONAL_FIELDS` pattern in `settings.py` — new fields must be added to both sets.
- `store.py` cannot import `settings.py` at module level (circular import: `settings.py` imports `_data_dir` from `store.py`). Import lazily inside `get_client()`.
- No data migration between local and remote Qdrant (spec non-goal) — do not implement any sync/copy logic.
- Match existing CLI help text and console output style (`[green]...[/green]`, `scope = "project" if project else "global"`).

---

### Task 1: Add `qdrant_url` / `qdrant_api_key` to `Settings`

**Files:**
- Modify: `src/yacodebase_mcp/settings.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `Settings.qdrant_url: str | None = None`, `Settings.qdrant_api_key: str | None = None`, both included in `_FIELDS` and `_OPTIONAL_FIELDS`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_settings.py`:

```python
def test_qdrant_settings_round_trip(tmp_path):
    from yacodebase_mcp.settings import Settings, load_settings, save_settings

    save_settings(Settings(qdrant_url="http://qdrant.internal:6333", qdrant_api_key="qk-test"))
    loaded = load_settings()
    assert loaded.qdrant_url == "http://qdrant.internal:6333"
    assert loaded.qdrant_api_key == "qk-test"


def test_qdrant_settings_omitted_when_none():
    from yacodebase_mcp.settings import Settings, save_settings, _settings_path

    save_settings(Settings(qdrant_url=None, qdrant_api_key=None))
    data = __import__("json").loads(_settings_path().read_text())
    assert "qdrant_url" not in data
    assert "qdrant_api_key" not in data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_settings.py -k qdrant -v`
Expected: FAIL — `Settings` has no field `qdrant_url`.

- [ ] **Step 3: Implement**

In `src/yacodebase_mcp/settings.py`, change:

```python
_FIELDS = {"embedding_model", "vector_size", "api_key", "api_base", "max_chunk_chars"}
_OPTIONAL_FIELDS = {"api_key", "api_base"}
```

to:

```python
_FIELDS = {
    "embedding_model",
    "vector_size",
    "api_key",
    "api_base",
    "max_chunk_chars",
    "qdrant_url",
    "qdrant_api_key",
}
_OPTIONAL_FIELDS = {"api_key", "api_base", "qdrant_url", "qdrant_api_key"}
```

And add fields to the dataclass:

```python
@dataclass
class Settings:
    embedding_model: str = "text-embedding-3-small"
    vector_size: int = 1536
    api_key: str | None = None
    api_base: str | None = None
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_settings.py -v`
Expected: PASS (all tests, including the two new ones and pre-existing ones like `test_get_settings_ignores_unknown_fields`).

- [ ] **Step 5: Commit**

```bash
git add src/yacodebase_mcp/settings.py tests/test_settings.py
git commit -m "feat: add qdrant_url/qdrant_api_key settings fields"
```

---

### Task 2: `store.get_client()` connects to remote Qdrant when configured

**Files:**
- Modify: `src/yacodebase_mcp/store.py:43-45`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `Settings.qdrant_url`, `Settings.qdrant_api_key` from Task 1.
- Produces: `get_client(repo_path: str | None = None) -> QdrantClient` — new optional `repo_path` param, defaults to `None` (fully backward compatible with all existing zero-arg call sites).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_store.py`:

```python
def test_get_client_uses_local_path_by_default(tmp_path):
    from yacodebase_mcp.store import get_client, _qdrant_path

    client = get_client()
    # local mode: client talks to on-disk path, collection ops work without a server
    assert not client.collection_exists("nonexistent-collection")
    assert _qdrant_path().exists()


def test_get_client_uses_remote_url_when_configured(tmp_path, monkeypatch):
    from yacodebase_mcp.settings import Settings, save_settings
    import yacodebase_mcp.store as store_mod

    save_settings(Settings(qdrant_url="http://example.invalid:6333", qdrant_api_key="qk-test"))

    captured = {}

    class FakeQdrantClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(store_mod, "QdrantClient", FakeQdrantClient)

    store_mod.get_client()

    assert captured["url"] == "http://example.invalid:6333"
    assert captured["api_key"] == "qk-test"
    assert "path" not in captured
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_store.py -k get_client -v`
Expected: FAIL — `test_get_client_uses_remote_url_when_configured` fails because `get_client()` always uses the local path (captured `url`/`api_key` never set, or `KeyError`).

- [ ] **Step 3: Implement**

In `src/yacodebase_mcp/store.py`, replace:

```python
def get_client() -> QdrantClient:
    _qdrant_path().mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=str(_qdrant_path()))
```

with:

```python
def get_client(repo_path: str | None = None) -> QdrantClient:
    from .settings import load_settings

    settings = load_settings(repo_path)
    if settings.qdrant_url:
        return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    _qdrant_path().mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=str(_qdrant_path()))
```

(The `from .settings import load_settings` is deliberately local to `get_client` — `settings.py` imports `_data_dir` from `store.py` at module level, so a top-level import here would be circular.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_store.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add src/yacodebase_mcp/store.py tests/test_store.py
git commit -m "feat: connect to remote qdrant when qdrant_url is configured"
```

---

### Task 3: Pass `repo_path` through in `indexer.py` for project-scoped overrides

**Files:**
- Modify: `src/yacodebase_mcp/indexer.py:138`, `src/yacodebase_mcp/indexer.py:182`
- Test: `tests/test_indexer.py`

**Interfaces:**
- Consumes: `get_client(repo_path: str | None = None)` from Task 2.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_indexer.py`, near the other `index_repo` tests (e.g. after `test_index_repo_saves_to_config`). Reuse the existing `fixture_repo` fixture and `_mock_openai()` helper already defined in this file — do not redefine them:

```python
def test_index_repo_passes_repo_path_to_get_client(fixture_repo, monkeypatch):
    import yacodebase_mcp.indexer as indexer_mod

    captured = {}
    real_get_client = indexer_mod.get_client

    def spy_get_client(repo_path=None):
        captured["repo_path"] = repo_path
        return real_get_client(repo_path)

    monkeypatch.setattr(indexer_mod, "get_client", spy_get_client)

    with patch("yacodebase_mcp.indexer.OpenAI") as MockOpenAI:
        MockOpenAI.return_value = _mock_openai()
        indexer_mod.index_repo(str(fixture_repo))

    assert captured["repo_path"] == str(fixture_repo.resolve())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_indexer.py -k passes_repo_path -v`
Expected: FAIL — `captured["repo_path"]` is `None` because `index_repo` currently calls `get_client()` with no args.

- [ ] **Step 3: Implement**

In `src/yacodebase_mcp/indexer.py`, in `index_repo` (around line 138):

```python
    qdrant = get_client(repo_path=abs_path)
```

and in `index_repo_incremental` (around line 182):

```python
    qdrant = get_client(repo_path=abs_path)
```

(`abs_path` is already computed as `str(Path(repo_path).resolve())` at the top of both functions.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_indexer.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add src/yacodebase_mcp/indexer.py tests/test_indexer.py
git commit -m "feat: use project-scoped qdrant settings when indexing"
```

---

### Task 4: CLI `config set qdrant-url` / `config set qdrant-api-key`

**Files:**
- Modify: `src/yacodebase_mcp/cli.py` (add after `set_api_base`, around line 172)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `patch_setting`, `unset_settings_fields` (already imported in `cli.py`), `qdrant_url`/`qdrant_api_key` fields from Task 1.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
def test_config_set_qdrant_url(runner):
    from yacodebase_mcp.settings import get_settings

    result = runner.invoke(main, ["config", "set", "qdrant-url", "http://qdrant.internal:6333"])
    assert result.exit_code == 0
    assert get_settings().qdrant_url == "http://qdrant.internal:6333"


def test_config_set_qdrant_api_key(runner):
    from yacodebase_mcp.settings import get_settings

    result = runner.invoke(main, ["config", "set", "qdrant-api-key", "qk-testkey"])
    assert result.exit_code == 0
    assert get_settings().qdrant_api_key == "qk-testkey"


def test_config_list_shows_masked_qdrant_api_key(runner):
    runner.invoke(main, ["config", "set", "qdrant-url", "http://qdrant.internal:6333"])
    runner.invoke(main, ["config", "set", "qdrant-api-key", "qk-abcdefgh"])
    result = runner.invoke(main, ["config", "list"])
    assert result.exit_code == 0
    assert "http://qdrant.internal:6333" in result.output
    assert "qk-abcdefgh" not in result.output
    assert "qk-ab***" in result.output


def test_config_unset_qdrant_url(runner):
    from yacodebase_mcp.settings import get_settings

    runner.invoke(main, ["config", "set", "qdrant-url", "http://qdrant.internal:6333"])
    result = runner.invoke(main, ["config", "unset", "qdrant-url"])
    assert result.exit_code == 0
    assert get_settings().qdrant_url is None


def test_config_unset_qdrant_api_key(runner):
    from yacodebase_mcp.settings import get_settings

    runner.invoke(main, ["config", "set", "qdrant-api-key", "qk-testkey"])
    result = runner.invoke(main, ["config", "unset", "qdrant-api-key"])
    assert result.exit_code == 0
    assert get_settings().qdrant_api_key is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_cli.py -k qdrant -v`
Expected: FAIL — `config set qdrant-url` is not a recognized command (Click `UsageError`/non-zero exit code).

- [ ] **Step 3: Implement**

In `src/yacodebase_mcp/cli.py`, after `set_api_base` (after line 172), add:

```python
@config_set.command("qdrant-url")
@click.argument("url")
@_project_opt
def set_qdrant_url(url: str, project: bool) -> None:
    """Set the URL of a remote Qdrant server (self-hosted or Qdrant Cloud). Unset to use local on-disk Qdrant."""
    project_path = os.getcwd() if project else None
    patch_setting("qdrant_url", url, project_path=project_path)
    scope = "project" if project else "global"
    console.print(f"[green]qdrant_url={url} ({scope})[/green]")


@config_set.command("qdrant-api-key")
@click.argument("key")
@_project_opt
def set_qdrant_api_key(key: str, project: bool) -> None:
    """Set the API key for a remote Qdrant server (e.g. Qdrant Cloud)."""
    project_path = os.getcwd() if project else None
    if project:
        console.print("[yellow]Warning: qdrant_api_key in project file may be exposed in git.[/yellow]")
    patch_setting("qdrant_api_key", key, project_path=project_path)
    scope = "project" if project else "global"
    console.print(f"[green]qdrant_api_key set ({scope}).[/green]")
```

In `config_list` (around line 189-214), add rows after `table.add_row("api_base", ...)`:

```python
    if s.qdrant_api_key:
        masked_qdrant_key = (
            (s.qdrant_api_key[:5] + "***")
            if len(s.qdrant_api_key) > 5
            else (s.qdrant_api_key + "***")
        )
    else:
        masked_qdrant_key = "(not set)"
```
(place this alongside the existing `masked_key` computation, before `table = Table(...)`)

and add table rows after the `max_chunk_chars` row:

```python
    table.add_row("qdrant_url", s.qdrant_url or "(not set, using local)")
    table.add_row("qdrant_api_key", masked_qdrant_key)
```

In `config_unset` (around line 218-233), update:

```python
@config.command("unset")
@click.argument(
    "key",
    type=click.Choice(
        ["embedding-model", "api-key", "api-base", "max-chunk-chars", "qdrant-url", "qdrant-api-key"]
    ),
)
@_project_opt
def config_unset(key: str, project: bool) -> None:
    """Remove a setting, reverting to default or env var fallback."""
    field_map = {
        "embedding-model": ["embedding_model", "vector_size"],
        "api-key": ["api_key"],
        "api-base": ["api_base"],
        "max-chunk-chars": ["max_chunk_chars"],
        "qdrant-url": ["qdrant_url"],
        "qdrant-api-key": ["qdrant_api_key"],
    }
    project_path = os.getcwd() if project else None
    unset_settings_fields(field_map[key], project_path=project_path)
    scope = "project" if project else "global"
    console.print(f"[green]{key} unset ({scope}).[/green]")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_cli.py -v`
Expected: PASS (all tests, including pre-existing `test_config_list_defaults` — check it doesn't assert an exact row count/exact output that the two new rows would break; if it does, update that assertion to account for the new rows).

- [ ] **Step 5: Commit**

```bash
git add src/yacodebase_mcp/cli.py tests/test_cli.py
git commit -m "feat: add config set/unset qdrant-url and qdrant-api-key CLI commands"
```

---

### Task 5: Full test suite + lint pass

**Files:** none (verification only)

- [ ] **Step 1: Run full test suite**

Run: `uv run python -m pytest -v`
Expected: PASS, all tests green.

- [ ] **Step 2: Run lint**

Run: `uv run ruff check src tests`
Expected: no violations.

- [ ] **Step 3: Run format check**

Run: `uv run ruff format --check src tests`
Expected: no changes needed. If it reports files needing formatting, run `uv run ruff format src tests` and review the diff before committing.

- [ ] **Step 4: Commit (only if Step 3 produced formatting changes)**

```bash
git add -u
git commit -m "style: apply ruff format"
```
