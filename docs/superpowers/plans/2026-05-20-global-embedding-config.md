# Global Embedding Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persistent global config for embedding model, API key, and API host in `~/.codebase-mcp/settings.json`, with a `codebase-mcp config` CLI group and mismatch detection when model changes.

**Architecture:** New `settings.py` module owns `Settings` dataclass and file I/O. `indexer.py` and `searcher.py` call `get_settings()` to build the `OpenAI` client and pick the model. `store.py`'s `ensure_collection` receives `vector_size` explicitly. CLI gains a `config` group with `set`, `list`, and `unset` subcommands.

**Tech Stack:** Python dataclasses, `json`, Click groups, `qdrant_client` collection info API, OpenAI SDK kwargs (`api_key`, `base_url`)

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `src/codebase_mcp/settings.py` | `Settings` dataclass, load/save/get, `KNOWN_MODELS` table |
| Modify | `src/codebase_mcp/store.py` | `ensure_collection` takes explicit `vector_size`; remove `VECTOR_SIZE` constant |
| Modify | `src/codebase_mcp/indexer.py` | `index_repo` and `_embed_batch` consume settings |
| Modify | `src/codebase_mcp/searcher.py` | `search` consumes settings; detect vector size mismatch |
| Modify | `src/codebase_mcp/cli.py` | Add `config` group with `set`, `list`, `unset` |
| Create | `tests/test_settings.py` | Unit tests for `settings.py` |
| Modify | `tests/test_store.py` | Update `ensure_collection` calls to pass `vector_size` |
| Modify | `tests/test_searcher.py` | Update `_seeded_store` helper; add mismatch test |
| Modify | `tests/test_indexer.py` | Add settings mock; add model-propagation test |
| Modify | `tests/test_cli.py` | Tests for `config set/list/unset` commands |

---

## Task 1: Create `settings.py`

**Files:**
- Create: `src/codebase_mcp/settings.py`
- Create: `tests/test_settings.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_settings.py`:

```python
import json

import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEBASE_MCP_DATA_DIR", str(tmp_path))


def test_get_settings_returns_defaults_when_no_file():
    from codebase_mcp.settings import get_settings

    s = get_settings()
    assert s.embedding_model == "text-embedding-3-small"
    assert s.vector_size == 1536
    assert s.api_key is None
    assert s.api_base is None


def test_save_and_load_round_trip():
    from codebase_mcp.settings import Settings, get_settings, save_settings

    original = Settings(
        embedding_model="text-embedding-3-large",
        vector_size=3072,
        api_key="sk-test",
        api_base="http://localhost:11434/v1",
    )
    save_settings(original)
    loaded = get_settings()
    assert loaded.embedding_model == "text-embedding-3-large"
    assert loaded.vector_size == 3072
    assert loaded.api_key == "sk-test"
    assert loaded.api_base == "http://localhost:11434/v1"


def test_get_settings_ignores_unknown_fields(tmp_path):
    from pathlib import Path

    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({"embedding_model": "text-embedding-3-large", "vector_size": 3072, "mystery": "value"})
    )

    from codebase_mcp.settings import get_settings

    s = get_settings()
    assert s.embedding_model == "text-embedding-3-large"
    assert not hasattr(s, "mystery")


def test_save_settings_omits_none_fields(tmp_path):
    from pathlib import Path

    from codebase_mcp.settings import Settings, save_settings

    save_settings(Settings(api_key=None, api_base=None))
    data = json.loads((tmp_path / "settings.json").read_text())
    assert "api_key" not in data
    assert "api_base" not in data


def test_known_models_table():
    from codebase_mcp.settings import KNOWN_MODELS

    assert KNOWN_MODELS["text-embedding-3-small"] == 1536
    assert KNOWN_MODELS["text-embedding-3-large"] == 3072
    assert KNOWN_MODELS["text-embedding-ada-002"] == 1536
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd /path/to/codebase-mcp && .venv/bin/pytest tests/test_settings.py -v
```

Expected: `ModuleNotFoundError` or `ImportError` — `settings` module does not exist yet.

- [ ] **Step 3: Implement `settings.py`**

Create `src/codebase_mcp/settings.py`:

```python
import json
from dataclasses import asdict, dataclass

from .store import _data_dir

KNOWN_MODELS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}

_FIELDS = {"embedding_model", "vector_size", "api_key", "api_base"}


@dataclass
class Settings:
    embedding_model: str = "text-embedding-3-small"
    vector_size: int = 1536
    api_key: str | None = None
    api_base: str | None = None


def _settings_path():
    return _data_dir() / "settings.json"


def load_settings() -> Settings:
    path = _settings_path()
    if not path.exists():
        return Settings()
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return Settings()
    return Settings(**{k: v for k, v in data.items() if k in _FIELDS})


def save_settings(s: Settings) -> None:
    _data_dir().mkdir(parents=True, exist_ok=True)
    data = {k: v for k, v in asdict(s).items() if v is not None}
    _settings_path().write_text(json.dumps(data, indent=2))


def get_settings() -> Settings:
    return load_settings()
```

- [ ] **Step 4: Run tests to verify they pass**

```
.venv/bin/pytest tests/test_settings.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/codebase_mcp/settings.py tests/test_settings.py
git commit -m "feat: add settings module with Settings dataclass and file I/O"
```

---

## Task 2: Update `store.py` — `ensure_collection` takes explicit `vector_size`

**Files:**
- Modify: `src/codebase_mcp/store.py`
- Modify: `tests/test_store.py`
- Modify: `tests/test_searcher.py` (update `_seeded_store` helper only)

- [ ] **Step 1: Update `test_store.py` — add `vector_size` to all `ensure_collection` calls**

In `tests/test_store.py`, find the two `ensure_collection` calls and add `vector_size=1536`:

```python
def test_ensure_collection_creates_new(tmp_path):
    from codebase_mcp.store import ensure_collection, get_client, get_repo_id

    client = get_client()
    repo_id = get_repo_id(str(tmp_path / "repo"))
    ensure_collection(client, repo_id, vector_size=1536)
    assert client.collection_exists(repo_id)


def test_ensure_collection_replaces_existing(tmp_path):
    from qdrant_client.models import PointStruct

    from codebase_mcp.store import ensure_collection, get_client, get_repo_id

    client = get_client()
    repo_id = get_repo_id(str(tmp_path / "repo"))
    ensure_collection(client, repo_id, vector_size=1536)
    client.upsert(
        collection_name=repo_id,
        points=[PointStruct(id=0, vector=[0.1] * 1536, payload={"x": 1})],
    )
    ensure_collection(client, repo_id, vector_size=1536)
    results = client.scroll(collection_name=repo_id, limit=10)[0]
    assert len(results) == 0
```

- [ ] **Step 2: Update `_seeded_store` in `test_searcher.py`**

In `tests/test_searcher.py`, update the `_seeded_store` helper (line ~32):

```python
def _seeded_store(tmp_path, repo_path: str, vector_size: int = 1536):
    """Put a fake repo entry in config + a real Qdrant collection with one point."""
    from qdrant_client.models import PointStruct

    from codebase_mcp.store import add_repo, ensure_collection, get_client, get_repo_id

    abs_path = str(Path(repo_path).resolve())
    repo_id = get_repo_id(abs_path)
    add_repo(abs_path, chunk_count=1)
    client = get_client()
    ensure_collection(client, repo_id, vector_size=vector_size)
    client.upsert(
        collection_name=repo_id,
        points=[
            PointStruct(
                id=0,
                vector=[0.1] * vector_size,
                payload={
                    "file": "main.py",
                    "start_line": 1,
                    "end_line": 5,
                    "repo_path": abs_path,
                    "text": "print('hello')",
                },
            )
        ],
    )
    return abs_path
```

- [ ] **Step 3: Run existing tests to verify they pass before changing `store.py`**

```
.venv/bin/pytest tests/test_store.py tests/test_searcher.py -v
```

Expected: FAIL on `test_store.py` (signature mismatch) — good, tests drive the implementation.

- [ ] **Step 4: Update `store.py`**

In `src/codebase_mcp/store.py`:

1. Remove line 10: `VECTOR_SIZE = 1536  # text-embedding-3-small`

2. Update `ensure_collection` signature:

```python
def ensure_collection(client: QdrantClient, repo_id: str, vector_size: int) -> None:
    if client.collection_exists(collection_name=repo_id):
        client.delete_collection(collection_name=repo_id)
    client.create_collection(
        collection_name=repo_id,
        vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
    )
```

- [ ] **Step 5: Run all tests**

```
.venv/bin/pytest tests/test_store.py tests/test_searcher.py tests/test_indexer.py -v
```

Expected: `test_store.py` and `test_searcher.py` PASS. `test_indexer.py` will FAIL on `ensure_collection` call — fix in Task 3.

- [ ] **Step 6: Commit**

```bash
git add src/codebase_mcp/store.py tests/test_store.py tests/test_searcher.py
git commit -m "refactor: ensure_collection takes explicit vector_size parameter"
```

---

## Task 3: Update `indexer.py` to use settings

**Files:**
- Modify: `src/codebase_mcp/indexer.py`
- Modify: `tests/test_indexer.py`

- [ ] **Step 1: Add settings-propagation test to `test_indexer.py`**

Add this test at the bottom of `tests/test_indexer.py`:

```python
def test_index_repo_uses_settings_model_and_credentials(fixture_repo):
    from codebase_mcp.indexer import index_repo
    from codebase_mcp.settings import Settings

    custom_settings = Settings(
        embedding_model="text-embedding-3-large",
        vector_size=3072,
        api_key="sk-custom",
        api_base="http://localhost:11434/v1",
    )

    def fake_create(model, input):
        assert model == "text-embedding-3-large"
        num = len(input) if isinstance(input, list) else 1
        return MagicMock(data=[MagicMock(embedding=[0.1] * 3072) for _ in range(num)])

    mock_client = MagicMock()
    mock_client.embeddings.create.side_effect = fake_create

    with (
        patch("codebase_mcp.indexer.get_settings", return_value=custom_settings),
        patch("codebase_mcp.indexer.OpenAI") as MockOpenAI,
    ):
        MockOpenAI.return_value = mock_client
        index_repo(str(fixture_repo))

    MockOpenAI.assert_called_once_with(api_key="sk-custom", base_url="http://localhost:11434/v1")
```

- [ ] **Step 2: Run test to verify it fails**

```
.venv/bin/pytest tests/test_indexer.py::test_index_repo_uses_settings_model_and_credentials -v
```

Expected: FAIL — `get_settings` not imported in `indexer.py` yet; also `ensure_collection` call still uses old signature.

- [ ] **Step 3: Update `indexer.py`**

Replace the contents of `src/codebase_mcp/indexer.py` with:

```python
import os
import time
from pathlib import Path

from openai import OpenAI
from qdrant_client.models import PointStruct

from .ast_chunker import chunk_file_ast
from .settings import get_settings
from .store import (
    add_repo,
    ensure_collection,
    get_client,
    get_repo_id,
)

INDEXED_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".rb",
    ".java",
    ".cpp",
    ".c",
    ".h",
    ".md",
    ".yaml",
    ".yml",
    ".toml",
    ".json",
    ".tf",
}
SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}
CHUNK_LINES = 100
OVERLAP_LINES = 20
MIN_LINES_FOR_SPLIT = 20
BATCH_SIZE = 100
MAX_CHUNK_CHARS = 32_000  # text-embedding-3-small limit is 8191 tokens (~4 chars/token)


def iter_files(repo_path: Path):
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for filename in files:
            filepath = Path(root) / filename
            if filepath.suffix in INDEXED_EXTENSIONS:
                yield filepath


def _chunk_file_lines(content: str, filepath: str, repo_path: str) -> list[dict]:
    lines = content.splitlines()
    if len(lines) < MIN_LINES_FOR_SPLIT:
        return [
            {
                "text": content[:MAX_CHUNK_CHARS],
                "file": filepath,
                "start_line": 1,
                "end_line": len(lines),
                "repo_path": repo_path,
            }
        ]

    chunks = []
    step = CHUNK_LINES - OVERLAP_LINES
    for i in range(0, len(lines), step):
        chunk_lines = lines[i : i + CHUNK_LINES]
        if not any(line.strip() for line in chunk_lines):
            continue
        text = "\n".join(chunk_lines)[:MAX_CHUNK_CHARS]
        chunks.append(
            {
                "text": text,
                "file": filepath,
                "start_line": i + 1,
                "end_line": i + len(chunk_lines),
                "repo_path": repo_path,
            }
        )
    return chunks


def chunk_file(content: str, filepath: str, repo_path: str) -> list[dict]:
    try:
        chunks = chunk_file_ast(content, filepath, repo_path)
    except Exception:
        chunks = None
    return chunks if chunks else _chunk_file_lines(content, filepath, repo_path)


def _embed_batch(texts: list[str], client: OpenAI, model: str) -> list[list[float]]:
    for attempt in range(3):
        try:
            response = client.embeddings.create(
                model=model,
                input=texts,
            )
            return [r.embedding for r in response.data]
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("Embedding failed after 3 attempts")


def index_repo(repo_path: str) -> int:
    """Index a repo. Always replaces any existing index for this path."""
    abs_path = str(Path(repo_path).resolve())
    repo_id = get_repo_id(abs_path)
    settings = get_settings()
    openai_client = OpenAI(api_key=settings.api_key, base_url=settings.api_base)
    qdrant = get_client()

    all_chunks: list[dict] = []
    for filepath in iter_files(Path(abs_path)):
        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        rel_path = str(filepath.relative_to(abs_path))
        all_chunks.extend(chunk_file(content, rel_path, abs_path))

    ensure_collection(qdrant, repo_id, vector_size=settings.vector_size)

    point_id = 0
    for i in range(0, len(all_chunks), BATCH_SIZE):
        batch = all_chunks[i : i + BATCH_SIZE]
        embeddings = _embed_batch([c["text"] for c in batch], openai_client, settings.embedding_model)
        points = [
            PointStruct(id=point_id + j, vector=emb, payload=chunk)
            for j, (chunk, emb) in enumerate(zip(batch, embeddings))
        ]
        qdrant.upsert(collection_name=repo_id, points=points)
        point_id += len(batch)

    add_repo(abs_path, len(all_chunks))
    return len(all_chunks)
```

- [ ] **Step 4: Run all indexer tests**

```
.venv/bin/pytest tests/test_indexer.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/codebase_mcp/indexer.py tests/test_indexer.py
git commit -m "feat: indexer reads embedding model, api_key, api_base from settings"
```

---

## Task 4: Update `searcher.py` to use settings + mismatch detection

**Files:**
- Modify: `src/codebase_mcp/searcher.py`
- Modify: `tests/test_searcher.py`

- [ ] **Step 1: Add mismatch test and settings test to `test_searcher.py`**

Add the following two tests at the bottom of `tests/test_searcher.py`:

```python
def test_search_uses_settings_model(tmp_path):
    abs_path = _seeded_store(tmp_path, str(tmp_path / "myrepo"))

    from codebase_mcp.settings import Settings

    custom_settings = Settings(
        embedding_model="custom-model",
        vector_size=1536,
        api_key="sk-custom",
        api_base="http://localhost/v1",
    )
    mock = MagicMock()
    mock.embeddings.create.return_value.data = [MagicMock(embedding=_fake_embedding())]

    with (
        patch("codebase_mcp.searcher.get_settings", return_value=custom_settings),
        patch("codebase_mcp.searcher.OpenAI") as MockOpenAI,
    ):
        MockOpenAI.return_value = mock
        from codebase_mcp.searcher import search

        search("hello", repo_path=abs_path)

    MockOpenAI.assert_called_once_with(api_key="sk-custom", base_url="http://localhost/v1")
    mock.embeddings.create.assert_called_once()
    call_kwargs = mock.embeddings.create.call_args
    assert call_kwargs.kwargs["model"] == "custom-model"


def test_search_returns_mismatch_warning(tmp_path):
    # Seed store with vector_size=1536, then search with settings that say 3072.
    abs_path = _seeded_store(tmp_path, str(tmp_path / "myrepo"), vector_size=1536)

    from codebase_mcp.settings import Settings

    mismatched_settings = Settings(
        embedding_model="text-embedding-3-large",
        vector_size=3072,
    )

    with patch("codebase_mcp.searcher.get_settings", return_value=mismatched_settings):
        from codebase_mcp.searcher import search

        result = search("hello", repo_path=abs_path)

    assert "mismatch" in result.lower()
    assert "reindex" in result.lower()
```

- [ ] **Step 2: Run new tests to verify they fail**

```
.venv/bin/pytest tests/test_searcher.py::test_search_uses_settings_model tests/test_searcher.py::test_search_returns_mismatch_warning -v
```

Expected: FAIL — `searcher.py` still uses hardcoded `OpenAI()` without settings.

- [ ] **Step 3: Update `searcher.py`**

Replace `src/codebase_mcp/searcher.py` with:

```python
from pathlib import Path

from openai import OpenAI

from .settings import get_settings
from .store import get_client, load_config

TOP_K = 8


def search(query: str, repo_path: str | None = None) -> str:
    config = load_config()

    if repo_path:
        abs_path = str(Path(repo_path).resolve())
        if abs_path not in config:
            return f"Repo not indexed. Run: codebase-mcp index {repo_path}"
        candidates = {abs_path: config[abs_path]}
    else:
        if not config:
            return "No repos indexed. Run: codebase-mcp index /path/to/repo"
        candidates = config

    settings = get_settings()
    openai_client = OpenAI(api_key=settings.api_key, base_url=settings.api_base)

    response = openai_client.embeddings.create(
        model=settings.embedding_model,
        input=[query],
    )
    query_vector = response.data[0].embedding

    qdrant = get_client()
    warnings: list[str] = []
    all_results = []

    for path, meta in candidates.items():
        repo_id = meta["repo_id"]
        try:
            info = qdrant.get_collection(repo_id)
            actual_size = info.config.params.vectors.size
        except Exception:
            continue
        if actual_size != settings.vector_size:
            warnings.append(
                f"⚠ Vector size mismatch for {path}: "
                f"indexed with {actual_size}, current model expects {settings.vector_size}. "
                f"Run: codebase-mcp reindex {path}"
            )
            continue
        try:
            results = qdrant.query_points(
                collection_name=repo_id,
                query=query_vector,
                limit=TOP_K,
            )
            all_results.extend(results.points)
        except Exception:
            continue

    warning_text = "\n".join(warnings)

    if not all_results:
        return warning_text if warning_text else "No results found."

    all_results.sort(key=lambda r: r.score, reverse=True)
    top = all_results[:TOP_K]

    parts = []
    for r in top:
        p = r.payload
        parts.append(
            f"### {p['file']} (lines {p['start_line']}-{p['end_line']}) — score: {r.score:.3f}\n"
            f"```\n{p['text']}\n```"
        )
    result_text = "\n\n".join(parts)
    return f"{warning_text}\n\n{result_text}".strip() if warning_text else result_text
```

- [ ] **Step 4: Run all searcher tests**

```
.venv/bin/pytest tests/test_searcher.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Run full test suite**

```
.venv/bin/pytest -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/codebase_mcp/searcher.py tests/test_searcher.py
git commit -m "feat: searcher reads settings, detects vector size mismatch"
```

---

## Task 5: Add `config` CLI command group

**Files:**
- Modify: `src/codebase_mcp/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Add the following tests at the bottom of `tests/test_cli.py`:

```python
def test_config_list_defaults(runner):
    from codebase_mcp.cli import main

    result = runner.invoke(main, ["config", "list"])
    assert result.exit_code == 0
    assert "text-embedding-3-small" in result.output
    assert "1536" in result.output


def test_config_set_known_model(runner):
    from codebase_mcp.cli import main
    from codebase_mcp.settings import get_settings

    result = runner.invoke(main, ["config", "set", "embedding-model", "text-embedding-3-large"])
    assert result.exit_code == 0
    s = get_settings()
    assert s.embedding_model == "text-embedding-3-large"
    assert s.vector_size == 3072


def test_config_set_unknown_model_without_vector_size_fails(runner):
    from codebase_mcp.cli import main

    result = runner.invoke(main, ["config", "set", "embedding-model", "nomic-embed-text"])
    assert result.exit_code != 0
    assert "vector-size" in result.output.lower()


def test_config_set_unknown_model_with_vector_size(runner):
    from codebase_mcp.cli import main
    from codebase_mcp.settings import get_settings

    result = runner.invoke(
        main, ["config", "set", "embedding-model", "nomic-embed-text", "--vector-size", "768"]
    )
    assert result.exit_code == 0
    s = get_settings()
    assert s.embedding_model == "nomic-embed-text"
    assert s.vector_size == 768


def test_config_set_api_key(runner):
    from codebase_mcp.cli import main
    from codebase_mcp.settings import get_settings

    result = runner.invoke(main, ["config", "set", "api-key", "sk-testkey"])
    assert result.exit_code == 0
    assert get_settings().api_key == "sk-testkey"


def test_config_set_api_base(runner):
    from codebase_mcp.cli import main
    from codebase_mcp.settings import get_settings

    result = runner.invoke(main, ["config", "set", "api-base", "http://localhost:11434/v1"])
    assert result.exit_code == 0
    assert get_settings().api_base == "http://localhost:11434/v1"


def test_config_list_shows_masked_api_key(runner):
    from codebase_mcp.cli import main

    runner.invoke(main, ["config", "set", "api-key", "sk-abcdefgh"])
    result = runner.invoke(main, ["config", "list"])
    assert result.exit_code == 0
    assert "sk-ab" in result.output
    assert "***" in result.output
    assert "sk-abcdefgh" not in result.output


def test_config_unset_api_key(runner):
    from codebase_mcp.cli import main
    from codebase_mcp.settings import get_settings

    runner.invoke(main, ["config", "set", "api-key", "sk-testkey"])
    result = runner.invoke(main, ["config", "unset", "api-key"])
    assert result.exit_code == 0
    assert get_settings().api_key is None


def test_config_unset_embedding_model_resets_vector_size(runner):
    from codebase_mcp.cli import main
    from codebase_mcp.settings import get_settings

    runner.invoke(main, ["config", "set", "embedding-model", "text-embedding-3-large"])
    assert get_settings().vector_size == 3072

    result = runner.invoke(main, ["config", "unset", "embedding-model"])
    assert result.exit_code == 0
    s = get_settings()
    assert s.embedding_model == "text-embedding-3-small"
    assert s.vector_size == 1536
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv/bin/pytest tests/test_cli.py -k "config" -v
```

Expected: FAIL — `config` command group does not exist yet.

- [ ] **Step 3: Add `unset_settings_fields` helper to `settings.py`**

Add this function at the bottom of `src/codebase_mcp/settings.py`:

```python
def unset_settings_fields(keys: list[str]) -> None:
    """Remove specific keys from settings.json; falling back to defaults on next load."""
    path = _settings_path()
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        data = {}
    for k in keys:
        data.pop(k, None)
    _data_dir().mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
```

- [ ] **Step 4: Add `config` group to `cli.py`**

Add the following to `src/codebase_mcp/cli.py` after the existing imports and before or after the existing commands (but inside the file — do not replace existing code):

First, add `get_settings`, `save_settings`, `unset_settings_fields`, `KNOWN_MODELS` to the imports section:

```python
from .settings import KNOWN_MODELS, get_settings, save_settings, unset_settings_fields
```

Then add the `config` group and its subcommands at the end of the file (before or after `serve`):

```python
@main.group()
def config():
    """Manage global settings (embedding model, API key, API host)."""


@config.group("set")
def config_set():
    """Set a config value."""


@config_set.command("embedding-model")
@click.argument("model")
@click.option("--vector-size", type=int, default=None, help="Vector dimension (required for unknown models).")
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
```

- [ ] **Step 5: Run all CLI tests**

```
.venv/bin/pytest tests/test_cli.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Run full test suite**

```
.venv/bin/pytest -v
```

Expected: all tests PASS, no regressions.

- [ ] **Step 7: Lint check**

```
.venv/bin/ruff check src/ tests/ && .venv/bin/ruff format --check src/ tests/
```

Fix any issues before committing.

- [ ] **Step 8: Commit**

```bash
git add src/codebase_mcp/cli.py src/codebase_mcp/settings.py tests/test_cli.py
git commit -m "feat: add config CLI group with set/list/unset commands"
```
