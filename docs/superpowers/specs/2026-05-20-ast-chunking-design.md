# AST-Based Chunking — Design Spec

**Date:** 2026-05-20  
**Status:** Approved

---

## Overview

Replace sliding-window line chunking with tree-sitter AST-based chunking for supported languages. Each semantic unit (function, method, Terraform block) becomes one chunk. Files without semantic nodes or unsupported extensions fall back to the existing line-window chunker. The public API of `indexer.py` is unchanged.

---

## Architecture

```
src/codebase_mcp/
├── indexer.py       ← modify: chunk_file becomes dispatcher, rename existing to _chunk_file_lines
└── ast_chunker.py   ← new: tree-sitter parsing, returns None on failure/unsupported
```

---

## Components

### `ast_chunker.py` (new)

Single public function:

**`chunk_file_ast(content: str, filepath: str, repo_path: str) -> list[dict] | None`**

Returns `None` when:
- Extension not in supported languages
- tree-sitter package unavailable (ImportError)
- Parsed AST has no semantic nodes (e.g. file is only imports/constants)

Returns `list[dict]` with same schema as existing chunks:
```python
{
    "text": str,        # node source text, truncated at MAX_CHUNK_CHARS
    "file": str,        # relative path
    "start_line": int,  # 1-indexed
    "end_line": int,    # 1-indexed
    "repo_path": str,   # absolute repo path
    "node_type": str,   # e.g. "function_definition", "block" — extra field for display
}
```

**Internals:**

- `EXT_TO_LANG: dict[str, str]` — maps file extension to language name
- `SEMANTIC_NODES: dict[str, set[str]]` — node type names to extract per language
- Parsers are lazy-initialized per language on first use (not at import time)
- AST walk is recursive; when a semantic node is found, it is extracted and children are NOT descended (avoids nested method-inside-class duplication)
- `ERROR` nodes in the AST are silently ignored

### `indexer.py` (modify)

- Rename `chunk_file` → `_chunk_file_lines` (no logic change)
- New `chunk_file` dispatcher:

```python
def chunk_file(content: str, filepath: str, repo_path: str) -> list[dict]:
    try:
        chunks = chunk_file_ast(content, filepath, repo_path)
    except Exception:
        chunks = None
    return chunks if chunks else _chunk_file_lines(content, filepath, repo_path)
```

- Add `.tf` to `INDEXED_EXTENSIONS`
- `index_repo` unchanged

---

## Supported Languages

| Extension(s) | Language | Semantic node types |
|---|---|---|
| `.py` | python | `function_definition`, `decorated_definition` |
| `.ts`, `.tsx` | typescript | `function_declaration`, `method_definition`, `arrow_function` |
| `.js`, `.jsx` | javascript | `function_declaration`, `method_definition`, `arrow_function` |
| `.go` | go | `function_declaration`, `method_declaration` |
| `.rs` | rust | `function_item` |
| `.java` | java | `method_declaration`, `constructor_declaration` |
| `.tf` | hcl | `block` (resource, data, module, variable, output, locals) |

**Fallback (line window):** All other extensions + any file where AST yields no semantic nodes.

---

## Error Handling

| Scenario | Behavior |
|---|---|
| Extension not in `EXT_TO_LANG` | Return `None` → fallback |
| `tree-sitter-<lang>` not installed | Catch `ImportError` in lazy init → return `None` → fallback |
| Parse produces only `ERROR` nodes | No semantic nodes found → return `None` → fallback |
| File has only imports/constants | No semantic nodes → return `None` → fallback |
| Chunk text > `MAX_CHUNK_CHARS` | Truncate (same as line chunker) |
| Any unexpected exception in AST path | `chunk_file` catches in dispatcher → fallback |

---

## Dependencies

Add to `pyproject.toml`:

```toml
"tree-sitter>=0.23",
"tree-sitter-python>=0.23",
"tree-sitter-typescript>=0.23",
"tree-sitter-javascript>=0.23",
"tree-sitter-go>=0.23",
"tree-sitter-rust>=0.23",
"tree-sitter-java>=0.23",
"tree-sitter-hcl>=0.23",
```

---

## Tests

### New: `tests/test_ast_chunker.py`

| Test | Verifies |
|---|---|
| `test_python_extracts_functions` | 2 Python functions → 2 chunks with correct line numbers |
| `test_python_extracts_decorated` | `@decorator\ndef foo()` → 1 chunk (decorated_definition) |
| `test_typescript_extracts_methods` | TS class with 2 methods → 2 chunks (not the class itself) |
| `test_go_extracts_functions` | 2 Go functions → 2 chunks |
| `test_rust_extracts_functions` | Standalone `fn` + `impl` method → 2 chunks |
| `test_java_extracts_methods` | Java class with 2 methods → 2 chunks |
| `test_terraform_extracts_blocks` | 2 `resource` blocks → 2 chunks |
| `test_unsupported_ext_returns_none` | `.yaml` filepath → returns `None` |
| `test_no_semantic_nodes_returns_none` | Python file with only imports → returns `None` |
| `test_chunk_file_falls_back_to_lines` | `.yaml` via `chunk_file` → line-based chunks |
| `test_chunk_file_uses_ast_for_python` | Python via `chunk_file` → chunks have `node_type` field |

### Modify: `tests/test_indexer.py`

- Update references: `chunk_file` → `_chunk_file_lines` in existing tests
- No other changes needed (integration tests still work via `chunk_file` dispatcher)

---

## Out of Scope

- C, C++, Ruby, YAML, TOML, JSON AST chunking
- Class-level chunks (spec: methods only)
- User-selectable chunking strategy
- Incremental re-index on file change
