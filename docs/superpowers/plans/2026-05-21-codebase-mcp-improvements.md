# Codebase MCP Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand yacodebase-mcp from 2 MCP tools to 11, add incremental indexing, and persist architectural knowledge across sessions.

**Architecture:** Four phases — (1) add structural MCP tools backed by AST chunker + Qdrant scroll, (2) incremental indexing via SHA256 file hashes stored in config.json, (3) SQLite knowledge layer for decisions/notes, (4) session bootstrap that wires everything together.

**Tech Stack:** Python 3.11+, tree-sitter, qdrant-client, openai, sqlite3 (stdlib), fastmcp, click

---

## File Map

| File | Action | What changes |
|---|---|---|
| `src/codebase_mcp/ast_chunker.py` | Modify | Add `symbol_name` extraction from AST nodes |
| `src/codebase_mcp/indexer.py` | Modify | Pass `symbol_name` to Qdrant payload; add incremental mode |
| `src/codebase_mcp/store.py` | Modify | Save/load `file_hashes` per repo in config.json |
| `src/codebase_mcp/server.py` | Modify | Add 9 new MCP tools |
| `src/codebase_mcp/knowledge.py` | Create | SQLite layer for decisions + notes |
| `tests/test_ast_chunker.py` | Modify | Add symbol_name assertions |
| `tests/test_server_tools.py` | Create | Tests for new MCP tools |
| `tests/test_knowledge.py` | Create | Tests for decisions/notes CRUD |
| `tests/test_incremental.py` | Create | Tests for incremental indexing |

---

## Phase 1 — More MCP Tools

### Task 1: Extract symbol names in AST chunker

**Files:**
- Modify: `src/codebase_mcp/ast_chunker.py`
- Modify: `tests/test_ast_chunker.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_ast_chunker.py — add to existing file
def test_chunk_has_symbol_name():
    content = "def my_function(x):\n    return x + 1\n"
    chunks = chunk_file_ast(content, "foo.py", "/repo")
    assert chunks is not None
    assert len(chunks) == 1
    assert chunks[0]["symbol_name"] == "my_function"

def test_chunk_symbol_name_class_method():
    content = "class Foo:\n    def bar(self):\n        pass\n"
    chunks = chunk_file_ast(content, "foo.py", "/repo")
    assert chunks is not None
    # class methods are not separate chunks (we don't descend into class bodies for methods)
    # but function_definition inside class IS a function_definition node
    names = [c["symbol_name"] for c in chunks]
    assert "bar" in names
```

- [ ] **Step 2: Run to verify fails**

```bash
cd /Users/gzamboni/Code/ai/codebase-mcp
.venv/bin/pytest tests/test_ast_chunker.py::test_chunk_has_symbol_name -v
```

Expected: `KeyError: 'symbol_name'`

- [ ] **Step 3: Add `_extract_symbol_name` and wire into `chunk_file_ast`**

In `src/codebase_mcp/ast_chunker.py`, add after the `_parsers` dict:

```python
def _extract_symbol_name(node, content: str) -> str | None:
    for child in node.children:
        if child.type in ("identifier", "property_identifier", "field_identifier", "name"):
            return content[child.start_byte : child.end_byte]
    return None
```

In `chunk_file_ast`, inside the `walk` function, change the chunk dict:

```python
        if node.type in node_types:
            text = content[node.start_byte : node.end_byte][:MAX_CHUNK_CHARS]
            chunks.append(
                {
                    "text": text,
                    "file": filepath,
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "repo_path": repo_path,
                    "node_type": node.type,
                    "symbol_name": _extract_symbol_name(node, content),
                }
            )
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_ast_chunker.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/codebase_mcp/ast_chunker.py tests/test_ast_chunker.py
git commit -m "feat: extract symbol_name from AST nodes in chunker"
```

---

### Task 2: Pass `symbol_name` through to Qdrant payload

**Files:**
- Modify: `src/codebase_mcp/indexer.py` (no test needed — payload passthrough)

The `indexer.py` already passes the full chunk dict as payload via `payload=chunk`. Since `chunk_file_ast` now includes `symbol_name`, and `_chunk_file_lines` does not, add `symbol_name: None` to the line-based chunks for consistency.

- [ ] **Step 1: Update `_chunk_file_lines` to include `symbol_name`**

In `src/codebase_mcp/indexer.py`, in `_chunk_file_lines`, change each dict to add:

```python
# In the short-file case:
return [
    {
        "text": content[:MAX_CHUNK_CHARS],
        "file": filepath,
        "start_line": 1,
        "end_line": len(lines),
        "repo_path": repo_path,
        "symbol_name": None,
    }
]

# In the sliding-window case, add to each chunk dict:
chunks.append(
    {
        "text": text,
        "file": filepath,
        "start_line": i + 1,
        "end_line": i + len(chunk_lines),
        "repo_path": repo_path,
        "symbol_name": None,
    }
)
```

- [ ] **Step 2: Run existing tests to confirm nothing broke**

```bash
.venv/bin/pytest tests/ -v
```

Expected: all pass

- [ ] **Step 3: Commit**

```bash
git add src/codebase_mcp/indexer.py
git commit -m "feat: include symbol_name in line-based chunk payload"
```

---

### Task 3: `get_file_outline` MCP tool

Returns list of all symbols in a file with their line ranges.

**Files:**
- Modify: `src/codebase_mcp/server.py`
- Create: `tests/test_server_tools.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_server_tools.py`:

```python
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from codebase_mcp.server import mcp


def _get_tool(name):
    """Get tool function from FastMCP server."""
    for tool in mcp._tool_manager._tools.values():
        if tool.name == name:
            return tool.fn
    raise KeyError(f"Tool {name!r} not registered")


def test_get_file_outline_python(tmp_path):
    src = tmp_path / "foo.py"
    src.write_text("def alpha():\n    pass\n\ndef beta(x, y):\n    return x + y\n")
    fn = _get_tool("get_file_outline")
    result = fn(file_path=str(src))
    assert "alpha" in result
    assert "beta" in result
    assert "1" in result  # line number

def test_get_file_outline_unsupported_file(tmp_path):
    src = tmp_path / "data.json"
    src.write_text('{"key": "value"}')
    fn = _get_tool("get_file_outline")
    result = fn(file_path=str(src))
    assert "No AST outline" in result or "data.json" in result
```

- [ ] **Step 2: Run to verify fails**

```bash
.venv/bin/pytest tests/test_server_tools.py::test_get_file_outline_python -v
```

Expected: `KeyError: 'get_file_outline'`

- [ ] **Step 3: Implement `get_file_outline` in `server.py`**

Add after the existing tools in `src/codebase_mcp/server.py`:

```python
from pathlib import Path
from . import searcher
from .ast_chunker import chunk_file_ast
from .store import get_all_repos


@mcp.tool()
def get_file_outline(file_path: str) -> str:
    """Return the structural outline (functions, methods, classes) of a source file.

    Args:
        file_path: Absolute path to the source file.
    """
    path = Path(file_path)
    if not path.exists():
        return f"File not found: {file_path}"
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return f"Cannot read file: {e}"

    chunks = chunk_file_ast(content, path.name, str(path.parent))
    if not chunks:
        return f"No AST outline available for {path.name} (unsupported language or no top-level symbols found)"

    lines = [f"## {path.name}"]
    for c in chunks:
        name = c.get("symbol_name") or "<anonymous>"
        lines.append(f"  {c['node_type']}  {name}  (lines {c['start_line']}–{c['end_line']})")
    return "\n".join(lines)
```

Also add `from pathlib import Path` and the `ast_chunker` import at the top of `server.py` (check if not already there):

```python
from pathlib import Path
from . import searcher
from .ast_chunker import chunk_file_ast
from .store import get_all_repos
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_server_tools.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/codebase_mcp/server.py tests/test_server_tools.py
git commit -m "feat: add get_file_outline MCP tool"
```

---

### Task 4: `search_symbols` MCP tool

Search indexed symbols by name substring using Qdrant scroll + payload filter.

**Files:**
- Modify: `src/codebase_mcp/server.py`
- Modify: `tests/test_server_tools.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_server_tools.py`:

```python
def test_search_symbols_no_repos():
    fn = _get_tool("search_symbols")
    with patch("codebase_mcp.server.get_all_repos", return_value={}):
        result = fn(name="anything")
    assert "No repos" in result

def test_search_symbols_returns_matches(tmp_path):
    """Integration-style: verify tool exists and returns a string."""
    fn = _get_tool("search_symbols")
    with patch("codebase_mcp.server.get_all_repos", return_value={}):
        result = fn(name="foo")
    assert isinstance(result, str)
```

- [ ] **Step 2: Run to verify fails**

```bash
.venv/bin/pytest tests/test_server_tools.py::test_search_symbols_no_repos -v
```

Expected: `KeyError: 'search_symbols'`

- [ ] **Step 3: Implement `search_symbols` in `server.py`**

Add to `src/codebase_mcp/server.py`:

```python
from qdrant_client.models import Filter, FieldCondition, MatchText, FilterSelector


@mcp.tool()
def search_symbols(name: str, repo_path: str | None = None) -> str:
    """Search for functions, methods, or classes by name across indexed repos.

    Args:
        name: Symbol name or substring to search (case-insensitive).
        repo_path: Absolute path to a specific repo. Omit to search all.
    """
    from .store import get_client, load_config
    from .settings import get_settings

    config = load_config()
    if not config:
        return "No repos indexed. Run: codebase-mcp index /path/to/repo"

    if repo_path:
        abs_path = str(Path(repo_path).resolve())
        candidates = {abs_path: config[abs_path]} if abs_path in config else {}
    else:
        candidates = config

    if not candidates:
        return f"Repo not indexed: {repo_path}"

    settings = get_settings()
    qdrant = get_client()
    results = []

    for path, meta in candidates.items():
        repo_id = meta["repo_id"]
        try:
            points, _ = qdrant.scroll(
                collection_name=repo_id,
                scroll_filter=Filter(
                    must=[FieldCondition(key="symbol_name", match=MatchText(text=name))]
                ),
                limit=50,
                with_payload=True,
                with_vectors=False,
            )
        except Exception:
            continue
        for p in points:
            pay = p.payload
            sym = pay.get("symbol_name") or "?"
            if name.lower() in sym.lower():  # double-check substring match
                results.append(
                    f"  {pay['node_type']}  {sym}  {pay['file']}:{pay['start_line']}-{pay['end_line']}"
                )

    if not results:
        return f"No symbols matching '{name}' found."
    header = f"Symbols matching '{name}':\n"
    return header + "\n".join(results)
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_server_tools.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/codebase_mcp/server.py tests/test_server_tools.py
git commit -m "feat: add search_symbols MCP tool"
```

---

### Task 5: `find_todos` MCP tool

Grep indexed file paths for TODO/FIXME/HACK/BUG comments.

**Files:**
- Modify: `src/codebase_mcp/server.py`
- Modify: `tests/test_server_tools.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_server_tools.py`:

```python
def test_find_todos_no_repos():
    fn = _get_tool("find_todos")
    with patch("codebase_mcp.server.get_all_repos", return_value={}):
        result = fn()
    assert "No repos" in result

def test_find_todos_finds_comment(tmp_path):
    src = tmp_path / "app.py"
    src.write_text("x = 1  # TODO: fix this\ny = 2\n# FIXME broken\n")
    fn = _get_tool("find_todos")
    # Call with explicit repo_path pointing to tmp_path
    with patch("codebase_mcp.server.get_all_repos", return_value={
        str(tmp_path): {"repo_id": "abc", "last_indexed": "2024-01-01T00:00:00Z", "chunk_count": 1}
    }):
        result = fn(repo_path=str(tmp_path))
    assert "TODO" in result or "FIXME" in result
```

- [ ] **Step 2: Run to verify fails**

```bash
.venv/bin/pytest tests/test_server_tools.py::test_find_todos_no_repos -v
```

Expected: `KeyError: 'find_todos'`

- [ ] **Step 3: Implement `find_todos` in `server.py`**

Add to `src/codebase_mcp/server.py`. This tool re-uses `indexer.iter_files` to walk files, so import it:

```python
from .indexer import iter_files
import re

TODO_PATTERN = re.compile(r"#\s*(TODO|FIXME|HACK|BUG|NOTE|XXX)\b[:\s]*(.*)", re.IGNORECASE)


@mcp.tool()
def find_todos(repo_path: str | None = None) -> str:
    """Find TODO, FIXME, HACK, BUG, NOTE comments in indexed repos.

    Args:
        repo_path: Absolute path to a specific repo. Omit to search all indexed repos.
    """
    config = get_all_repos()
    if not config:
        return "No repos indexed. Run: codebase-mcp index /path/to/repo"

    if repo_path:
        abs_path = str(Path(repo_path).resolve())
        candidates = {abs_path: config[abs_path]} if abs_path in config else {}
    else:
        candidates = config

    if not candidates:
        return f"Repo not indexed: {repo_path}"

    found: list[str] = []
    for path in candidates:
        for filepath in iter_files(Path(path)):
            try:
                text = filepath.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                m = TODO_PATTERN.search(line)
                if m:
                    rel = str(filepath.relative_to(path))
                    found.append(f"  [{m.group(1).upper()}] {rel}:{lineno}  {m.group(2).strip()}")

    if not found:
        return "No TODO/FIXME/HACK/BUG/NOTE comments found."
    return f"Found {len(found)} items:\n" + "\n".join(found)
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_server_tools.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/codebase_mcp/server.py tests/test_server_tools.py
git commit -m "feat: add find_todos MCP tool"
```

---

### Task 6: `what_changed` MCP tool

Report files added, modified, or deleted since last index.

**Files:**
- Modify: `src/codebase_mcp/server.py`
- Modify: `tests/test_server_tools.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_server_tools.py`:

```python
import time

def test_what_changed_no_repos():
    fn = _get_tool("what_changed")
    with patch("codebase_mcp.server.get_all_repos", return_value={}):
        result = fn()
    assert "No repos" in result

def test_what_changed_detects_modified(tmp_path):
    src = tmp_path / "app.py"
    src.write_text("x = 1\n")
    past_time = "2000-01-01T00:00:00+00:00"  # guaranteed old
    fn = _get_tool("what_changed")
    with patch("codebase_mcp.server.get_all_repos", return_value={
        str(tmp_path): {"repo_id": "abc", "last_indexed": past_time, "chunk_count": 1}
    }):
        result = fn(repo_path=str(tmp_path))
    assert "app.py" in result
    assert "modified" in result.lower() or "changed" in result.lower()
```

- [ ] **Step 2: Run to verify fails**

```bash
.venv/bin/pytest tests/test_server_tools.py::test_what_changed_no_repos -v
```

Expected: `KeyError: 'what_changed'`

- [ ] **Step 3: Implement `what_changed` in `server.py`**

```python
from datetime import datetime, timezone


@mcp.tool()
def what_changed(repo_path: str | None = None) -> str:
    """Show files added or modified since the last index run.

    Args:
        repo_path: Absolute path to a specific repo. Omit to check all indexed repos.
    """
    config = get_all_repos()
    if not config:
        return "No repos indexed. Run: codebase-mcp index /path/to/repo"

    if repo_path:
        abs_path = str(Path(repo_path).resolve())
        candidates = {abs_path: config[abs_path]} if abs_path in config else {}
    else:
        candidates = config

    if not candidates:
        return f"Repo not indexed: {repo_path}"

    parts: list[str] = []
    for path, meta in candidates.items():
        last_indexed = datetime.fromisoformat(meta["last_indexed"])
        if last_indexed.tzinfo is None:
            last_indexed = last_indexed.replace(tzinfo=timezone.utc)

        changed: list[str] = []
        for filepath in iter_files(Path(path)):
            mtime = datetime.fromtimestamp(filepath.stat().st_mtime, tz=timezone.utc)
            if mtime > last_indexed:
                rel = str(filepath.relative_to(path))
                changed.append(f"  modified  {rel}")

        if changed:
            parts.append(f"{path} ({len(changed)} changed since {meta['last_indexed'][:19]}):\n" + "\n".join(changed))
        else:
            parts.append(f"{path}: no changes since {meta['last_indexed'][:19]}")

    return "\n\n".join(parts)
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_server_tools.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/codebase_mcp/server.py tests/test_server_tools.py
git commit -m "feat: add what_changed MCP tool"
```

---

## Phase 2 — Incremental Indexing

### Task 7: Store file hashes in config.json

**Files:**
- Modify: `src/codebase_mcp/store.py`
- Create: `tests/test_incremental.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_incremental.py`:

```python
import hashlib
from pathlib import Path
from codebase_mcp.store import save_file_hashes, load_file_hashes


def test_save_and_load_file_hashes(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEBASE_MCP_DATA_DIR", str(tmp_path))
    # Must add repo first so config entry exists
    from codebase_mcp.store import add_repo, load_config
    add_repo("/test/repo", 10)

    hashes = {"src/a.py": "abc123", "src/b.py": "def456"}
    save_file_hashes("/test/repo", hashes)

    loaded = load_file_hashes("/test/repo")
    assert loaded == hashes

def test_load_file_hashes_missing_repo(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEBASE_MCP_DATA_DIR", str(tmp_path))
    from codebase_mcp.store import load_file_hashes
    result = load_file_hashes("/nonexistent/repo")
    assert result == {}
```

- [ ] **Step 2: Run to verify fails**

```bash
.venv/bin/pytest tests/test_incremental.py::test_save_and_load_file_hashes -v
```

Expected: `ImportError: cannot import name 'save_file_hashes'`

- [ ] **Step 3: Add `save_file_hashes` / `load_file_hashes` to `store.py`**

Add to `src/codebase_mcp/store.py`:

```python
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
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_incremental.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/codebase_mcp/store.py tests/test_incremental.py
git commit -m "feat: store per-file SHA256 hashes in config.json"
```

---

### Task 8: Incremental indexing in `indexer.py`

Only re-embed and re-insert files that have changed (SHA256 differs or file is new). Delete Qdrant points for removed/changed files before reinserting.

**Files:**
- Modify: `src/codebase_mcp/indexer.py`
- Modify: `tests/test_incremental.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_incremental.py`:

```python
from unittest.mock import patch, MagicMock, call


def test_index_incremental_skips_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEBASE_MCP_DATA_DIR", str(tmp_path / "data"))
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("def foo(): pass\n")

    from codebase_mcp.indexer import index_repo_incremental

    mock_qdrant = MagicMock()
    mock_qdrant.collection_exists.return_value = True
    mock_qdrant.get_collection.return_value = MagicMock(
        config=MagicMock(params=MagicMock(vectors=MagicMock(size=1536)))
    )

    mock_openai = MagicMock()
    mock_openai.embeddings.create.return_value = MagicMock(
        data=[MagicMock(embedding=[0.1] * 1536)]
    )

    with patch("codebase_mcp.indexer.get_client", return_value=mock_qdrant), \
         patch("codebase_mcp.indexer.OpenAI", return_value=mock_openai):
        count1 = index_repo_incremental(str(repo))
        count2 = index_repo_incremental(str(repo))  # second call: nothing changed

    # First call embeds a.py, second call skips it (hash unchanged)
    embed_calls = mock_openai.embeddings.create.call_count
    assert count1 > 0
    assert count2 == 0  # no new chunks processed
```

- [ ] **Step 2: Run to verify fails**

```bash
.venv/bin/pytest tests/test_incremental.py::test_index_incremental_skips_unchanged -v
```

Expected: `ImportError: cannot import name 'index_repo_incremental'`

- [ ] **Step 3: Add `index_repo_incremental` to `indexer.py`**

Add these imports at top of `src/codebase_mcp/indexer.py`:

```python
import hashlib
from qdrant_client.models import Filter, FieldCondition, MatchValue, FilterSelector
from .store import save_file_hashes, load_file_hashes
```

Add the function after `index_repo`:

```python
def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def index_repo_incremental(repo_path: str) -> int:
    """Index only changed/new files. Returns count of newly indexed chunks."""
    abs_path = str(Path(repo_path).resolve())
    repo_id = get_repo_id(abs_path)
    settings = get_settings()
    openai_client = OpenAI(api_key=settings.api_key, base_url=settings.api_base)
    qdrant = get_client()

    stored_hashes = load_file_hashes(abs_path)
    current_hashes: dict[str, str] = {}
    changed_files: list[Path] = []
    deleted_rel_paths: list[str] = []

    # Compute current hashes, detect changed/new files
    current_rel_paths: set[str] = set()
    for filepath in iter_files(Path(abs_path)):
        rel = str(filepath.relative_to(abs_path))
        current_rel_paths.add(rel)
        sha = _file_sha256(filepath)
        current_hashes[rel] = sha
        if stored_hashes.get(rel) != sha:
            changed_files.append(filepath)

    # Detect deleted files
    for rel in stored_hashes:
        if rel not in current_rel_paths:
            deleted_rel_paths.append(rel)

    # Ensure collection exists (create if first run)
    if not qdrant.collection_exists(collection_name=repo_id):
        from .store import ensure_collection
        ensure_collection(qdrant, repo_id, vector_size=settings.vector_size)

    # Delete chunks for changed + deleted files
    files_to_clear = [str(f.relative_to(abs_path)) for f in changed_files] + deleted_rel_paths
    for rel in files_to_clear:
        try:
            qdrant.delete(
                collection_name=repo_id,
                points_selector=FilterSelector(
                    filter=Filter(must=[FieldCondition(key="file", match=MatchValue(value=rel))])
                ),
            )
        except Exception:
            pass

    # Get next point ID (scroll to find max id)
    try:
        existing, _ = qdrant.scroll(collection_name=repo_id, limit=1, with_vectors=False, with_payload=False, order_by="id")
        # approximate: use collection count
        info = qdrant.get_collection(repo_id)
        point_id = info.points_count
    except Exception:
        point_id = 0

    # Embed and insert changed/new files
    all_new_chunks: list[dict] = []
    for filepath in changed_files:
        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        rel = str(filepath.relative_to(abs_path))
        all_new_chunks.extend(chunk_file(content, rel, abs_path))

    for c in all_new_chunks:
        c["text"] = c["text"][:MAX_CHUNK_CHARS]
    all_new_chunks = [c for c in all_new_chunks if c["text"].strip()]

    for i in range(0, len(all_new_chunks), BATCH_SIZE):
        batch = all_new_chunks[i : i + BATCH_SIZE]
        embeddings = _embed_batch([c["text"] for c in batch], openai_client, settings.embedding_model)
        points = [
            PointStruct(id=point_id + j, vector=emb, payload=chunk)
            for j, (chunk, emb) in enumerate(zip(batch, embeddings))
        ]
        qdrant.upsert(collection_name=repo_id, points=points)
        point_id += len(batch)

    # Update stored hashes and chunk count
    save_file_hashes(abs_path, current_hashes)
    # Update repo metadata (keep existing chunk_count approximate)
    from .store import load_config, save_config
    from datetime import datetime, timezone
    config = load_config()
    if abs_path in config:
        config[abs_path]["last_indexed"] = datetime.now(timezone.utc).isoformat()
        # Approximate: existing - deleted + new
        old_count = config[abs_path].get("chunk_count", 0)
        config[abs_path]["chunk_count"] = old_count + len(all_new_chunks)
        save_config(config)
    else:
        add_repo(abs_path, len(all_new_chunks))

    return len(all_new_chunks)
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_incremental.py -v
```

Expected: all pass

- [ ] **Step 5: Wire into CLI**

In `src/codebase_mcp/cli.py`, add an `update` command after the existing commands:

```python
@cli.command()
@click.argument("repo_path", type=click.Path(exists=True, file_okay=False))
def update(repo_path):
    """Incrementally update index for REPO_PATH (only changed files)."""
    from .indexer import index_repo_incremental
    from .store import is_indexed
    abs_path = str(Path(repo_path).resolve())
    if not is_indexed(abs_path):
        click.echo(f"Not indexed. Run: codebase-mcp index {repo_path}", err=True)
        raise SystemExit(1)
    count = index_repo_incremental(abs_path)
    if count == 0:
        click.echo("No changes detected. Index is up to date.")
    else:
        click.echo(f"Updated {count} chunks.")
```

- [ ] **Step 6: Run all tests**

```bash
.venv/bin/pytest tests/ -v
```

Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add src/codebase_mcp/indexer.py src/codebase_mcp/cli.py tests/test_incremental.py
git commit -m "feat: incremental indexing via SHA256 change detection"
```

---

## Phase 3 — Knowledge Persistence

### Task 9: SQLite knowledge layer

**Files:**
- Create: `src/codebase_mcp/knowledge.py`
- Create: `tests/test_knowledge.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_knowledge.py`:

```python
import pytest
from codebase_mcp.knowledge import add_decision, search_decisions, update_decision, add_note, get_notes


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEBASE_MCP_DATA_DIR", str(tmp_path))


def test_add_and_search_decision():
    add_decision("Use Qdrant", "Qdrant chosen for vector storage because in-process", "architecture")
    results = search_decisions("Qdrant")
    assert len(results) == 1
    assert results[0]["title"] == "Use Qdrant"
    assert results[0]["status"] == "active"

def test_search_decision_by_category():
    add_decision("Auth via JWT", "JWT for stateless auth", "security")
    add_decision("DB is Postgres", "Postgres for relational data", "architecture")
    results = search_decisions(category="security")
    assert len(results) == 1
    assert results[0]["title"] == "Auth via JWT"

def test_update_decision_status():
    add_decision("Old approach", "We used to do X", "architecture")
    results = search_decisions("Old approach")
    decision_id = results[0]["id"]
    update_decision(decision_id, status="superseded")
    updated = search_decisions("Old approach")
    assert updated[0]["status"] == "superseded"

def test_add_and_get_notes():
    add_note("Remember to update tests after refactor", scope="project")
    notes = get_notes()
    assert len(notes) == 1
    assert "tests" in notes[0]["content"]

def test_get_notes_by_scope():
    add_note("Note for auth module", scope="file", reference="src/auth.py")
    add_note("Project-wide note", scope="project")
    notes = get_notes(scope="file")
    assert len(notes) == 1
    assert notes[0]["reference"] == "src/auth.py"
```

- [ ] **Step 2: Run to verify fails**

```bash
.venv/bin/pytest tests/test_knowledge.py -v
```

Expected: `ModuleNotFoundError: No module named 'codebase_mcp.knowledge'`

- [ ] **Step 3: Create `src/codebase_mcp/knowledge.py`**

```python
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .store import _data_dir


def _db_path() -> Path:
    return _data_dir() / "knowledge.db"


def _conn() -> sqlite3.Connection:
    _data_dir().mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(_db_path()))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS decisions (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            title   TEXT NOT NULL,
            body    TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'general',
            status  TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS notes (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            content   TEXT NOT NULL,
            scope     TEXT NOT NULL DEFAULT 'project',
            reference TEXT,
            created_at TEXT NOT NULL
        );
    """)
    con.commit()
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def add_decision(title: str, body: str, category: str = "general") -> int:
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO decisions (title, body, category, status, created_at) VALUES (?,?,?,?,?)",
            (title, body, category, "active", _now()),
        )
        return cur.lastrowid


def search_decisions(query: str = "", category: str = "") -> list[dict]:
    con = _conn()
    sql = "SELECT * FROM decisions WHERE 1=1"
    params: list = []
    if query:
        sql += " AND (title LIKE ? OR body LIKE ?)"
        params += [f"%{query}%", f"%{query}%"]
    if category:
        sql += " AND category = ?"
        params.append(category)
    sql += " ORDER BY created_at DESC"
    rows = con.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def update_decision(decision_id: int, status: str) -> None:
    with _conn() as con:
        con.execute("UPDATE decisions SET status=? WHERE id=?", (status, decision_id))


def add_note(content: str, scope: str = "project", reference: str | None = None) -> int:
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO notes (content, scope, reference, created_at) VALUES (?,?,?,?)",
            (content, scope, reference, _now()),
        )
        return cur.lastrowid


def get_notes(scope: str = "") -> list[dict]:
    con = _conn()
    sql = "SELECT * FROM notes"
    params: list = []
    if scope:
        sql += " WHERE scope = ?"
        params.append(scope)
    sql += " ORDER BY created_at DESC"
    rows = con.execute(sql, params).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_knowledge.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/codebase_mcp/knowledge.py tests/test_knowledge.py
git commit -m "feat: SQLite knowledge layer for decisions and notes"
```

---

### Task 10: Decision and note MCP tools

**Files:**
- Modify: `src/codebase_mcp/server.py`
- Modify: `tests/test_server_tools.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_server_tools.py`:

```python
def test_add_decision_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEBASE_MCP_DATA_DIR", str(tmp_path))
    fn = _get_tool("add_decision")
    result = fn(title="Use SQLite", body="SQLite for knowledge persistence", category="architecture")
    assert "saved" in result.lower() or "decision" in result.lower()

def test_search_decisions_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEBASE_MCP_DATA_DIR", str(tmp_path))
    from codebase_mcp.knowledge import add_decision as _add
    _add("Use Qdrant", "Vector storage", "architecture")
    fn = _get_tool("search_decisions")
    result = fn(query="Qdrant")
    assert "Qdrant" in result

def test_add_note_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEBASE_MCP_DATA_DIR", str(tmp_path))
    fn = _get_tool("add_note")
    result = fn(content="Remember to add pagination", scope="project")
    assert "saved" in result.lower() or "note" in result.lower()

def test_get_notes_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEBASE_MCP_DATA_DIR", str(tmp_path))
    from codebase_mcp.knowledge import add_note as _add
    _add("pagination needed", scope="project")
    fn = _get_tool("get_notes")
    result = fn()
    assert "pagination" in result
```

- [ ] **Step 2: Run to verify fails**

```bash
.venv/bin/pytest tests/test_server_tools.py::test_add_decision_tool -v
```

Expected: `KeyError: 'add_decision'`

- [ ] **Step 3: Add knowledge tools to `server.py`**

```python
from .knowledge import (
    add_decision as _add_decision,
    search_decisions as _search_decisions,
    update_decision as _update_decision,
    add_note as _add_note,
    get_notes as _get_notes,
)


@mcp.tool()
def add_decision(title: str, body: str, category: str = "general") -> str:
    """Record an architectural decision for future sessions.

    Args:
        title: Short title for the decision.
        body: Detailed explanation of the decision and rationale.
        category: Category label (e.g. 'architecture', 'security', 'performance').
    """
    decision_id = _add_decision(title, body, category)
    return f"Decision #{decision_id} saved: {title}"


@mcp.tool()
def search_decisions(query: str = "", category: str = "") -> str:
    """Search recorded architectural decisions.

    Args:
        query: Keyword to search in title and body. Omit to list all.
        category: Filter by category. Omit to search all categories.
    """
    results = _search_decisions(query=query, category=category)
    if not results:
        return "No decisions found."
    lines = []
    for d in results:
        lines.append(f"[#{d['id']}] [{d['status']}] {d['title']} ({d['category']})\n  {d['body'][:120]}")
    return "\n\n".join(lines)


@mcp.tool()
def update_decision(decision_id: int, status: str) -> str:
    """Update the status of an architectural decision.

    Args:
        decision_id: The ID of the decision (from search_decisions output).
        status: New status: 'active', 'superseded', 'implemented', or 'rejected'.
    """
    valid = {"active", "superseded", "implemented", "rejected"}
    if status not in valid:
        return f"Invalid status '{status}'. Use one of: {', '.join(sorted(valid))}"
    _update_decision(decision_id, status)
    return f"Decision #{decision_id} status updated to '{status}'"


@mcp.tool()
def add_note(content: str, scope: str = "project", reference: str | None = None) -> str:
    """Save a note that persists across sessions.

    Args:
        content: The note text.
        scope: 'project', 'file', or 'symbol'.
        reference: File path or symbol name the note refers to (optional).
    """
    note_id = _add_note(content, scope, reference)
    return f"Note #{note_id} saved."


@mcp.tool()
def get_notes(scope: str = "") -> str:
    """Retrieve saved notes.

    Args:
        scope: Filter by scope ('project', 'file', 'symbol'). Omit for all notes.
    """
    notes = _get_notes(scope=scope)
    if not notes:
        return "No notes found."
    lines = []
    for n in notes:
        ref = f" [{n['reference']}]" if n.get("reference") else ""
        lines.append(f"[#{n['id']}] [{n['scope']}]{ref} {n['content']}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_server_tools.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/codebase_mcp/server.py tests/test_server_tools.py
git commit -m "feat: add decision and note MCP tools"
```

---

## Phase 4 — Session Bootstrap

### Task 11: `session_bootstrap` MCP tool

Single call that orients an agent: repos status, what changed, active decisions, active notes.

**Files:**
- Modify: `src/codebase_mcp/server.py`
- Modify: `tests/test_server_tools.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_server_tools.py`:

```python
def test_session_bootstrap_no_repos():
    fn = _get_tool("session_bootstrap")
    with patch("codebase_mcp.server.get_all_repos", return_value={}):
        result = fn()
    assert "No repos" in result or "indexed" in result.lower()

def test_session_bootstrap_returns_summary(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEBASE_MCP_DATA_DIR", str(tmp_path))
    from codebase_mcp.knowledge import add_decision as _add
    _add("Use SQLite", "For knowledge", "architecture")
    fn = _get_tool("session_bootstrap")
    with patch("codebase_mcp.server.get_all_repos", return_value={
        "/some/repo": {"repo_id": "abc", "last_indexed": "2000-01-01T00:00:00+00:00", "chunk_count": 42}
    }), patch("codebase_mcp.server.iter_files", return_value=[]):
        result = fn()
    assert "SQLite" in result
    assert "42" in result  # chunk count
```

- [ ] **Step 2: Run to verify fails**

```bash
.venv/bin/pytest tests/test_server_tools.py::test_session_bootstrap_no_repos -v
```

Expected: `KeyError: 'session_bootstrap'`

- [ ] **Step 3: Implement `session_bootstrap` in `server.py`**

```python
@mcp.tool()
def session_bootstrap(repo_path: str | None = None) -> str:
    """Orient the agent for a new session: repo status, recent changes, active decisions and notes.

    Call this at the start of every session instead of reading files for orientation.

    Args:
        repo_path: Absolute path to a specific repo. Omit to summarize all indexed repos.
    """
    sections: list[str] = ["# Session Bootstrap\n"]

    # --- Repos ---
    config = get_all_repos()
    if not config:
        return "No repos indexed. Run: codebase-mcp index /path/to/repo"

    if repo_path:
        abs_path = str(Path(repo_path).resolve())
        candidates = {abs_path: config[abs_path]} if abs_path in config else {}
    else:
        candidates = config

    repo_lines = ["## Indexed Repos"]
    for path, meta in candidates.items():
        repo_lines.append(
            f"  {path}  —  {meta['chunk_count']} chunks, last indexed {meta['last_indexed'][:19]}"
        )
    sections.append("\n".join(repo_lines))

    # --- What changed ---
    changed_parts: list[str] = []
    for path, meta in candidates.items():
        last_indexed = datetime.fromisoformat(meta["last_indexed"])
        if last_indexed.tzinfo is None:
            last_indexed = last_indexed.replace(tzinfo=timezone.utc)
        changed = []
        for filepath in iter_files(Path(path)):
            mtime = datetime.fromtimestamp(filepath.stat().st_mtime, tz=timezone.utc)
            if mtime > last_indexed:
                changed.append(str(filepath.relative_to(path)))
        if changed:
            changed_parts.append(f"{path}: {len(changed)} file(s) changed since last index")
    if changed_parts:
        sections.append("## Changes Since Last Index\n" + "\n".join(f"  {c}" for c in changed_parts))
    else:
        sections.append("## Changes Since Last Index\n  None detected")

    # --- Active decisions ---
    decisions = _search_decisions()
    active = [d for d in decisions if d["status"] == "active"]
    if active:
        dec_lines = ["## Active Decisions"]
        for d in active[:10]:
            dec_lines.append(f"  [#{d['id']}] {d['title']} ({d['category']})")
        sections.append("\n".join(dec_lines))

    # --- Recent notes ---
    notes = _get_notes()
    if notes:
        note_lines = ["## Notes"]
        for n in notes[:5]:
            ref = f" [{n['reference']}]" if n.get("reference") else ""
            note_lines.append(f"  [#{n['id']}]{ref} {n['content'][:80]}")
        sections.append("\n".join(note_lines))

    return "\n\n".join(sections)
```

- [ ] **Step 4: Run all tests**

```bash
.venv/bin/pytest tests/ -v
```

Expected: all pass

- [ ] **Step 5: Run lint**

```bash
.venv/bin/ruff check src tests
.venv/bin/ruff format src tests
```

Fix any issues reported.

- [ ] **Step 6: Commit**

```bash
git add src/codebase_mcp/server.py tests/test_server_tools.py
git commit -m "feat: add session_bootstrap MCP tool"
```

---

## Final Verification

- [ ] **Run full test suite**

```bash
.venv/bin/pytest tests/ -v
```

Expected: all pass, no warnings about missing fixtures

- [ ] **Verify tool count in server**

```bash
python -c "from codebase_mcp.server import mcp; tools = list(mcp._tool_manager._tools); print(f'{len(tools)} tools:', tools)"
```

Expected: 11 tools — `search_codebase`, `list_indexed_repos`, `get_file_outline`, `search_symbols`, `find_todos`, `what_changed`, `add_decision`, `search_decisions`, `update_decision`, `add_note`, `get_notes`, `session_bootstrap`

- [ ] **Build package to confirm no metadata issues**

```bash
uv build
```

Expected: `Successfully built dist/yacodebase_mcp-0.1.0-py3-none-any.whl`
