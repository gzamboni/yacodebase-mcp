import asyncio
from unittest.mock import patch

from codebase_mcp.server import mcp


def _get_tool(name):
    """Get tool function from FastMCP server."""
    tool = asyncio.run(mcp.get_tool(name))
    if tool is None:
        raise KeyError(f"Tool {name!r} not registered")
    return tool.fn


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


def test_get_file_outline_missing_file():
    fn = _get_tool("get_file_outline")
    result = fn(file_path="/nonexistent/path/foo.py")
    assert "not found" in result.lower() or "File not found" in result


def test_search_symbols_no_repos():
    fn = _get_tool("search_symbols")
    with patch("codebase_mcp.server.get_all_repos", return_value={}):
        result = fn(name="anything")
    assert "No repos" in result


def test_search_symbols_returns_string():
    fn = _get_tool("search_symbols")
    with patch("codebase_mcp.server.get_all_repos", return_value={}):
        result = fn(name="foo")
    assert isinstance(result, str)


def test_find_todos_no_repos():
    fn = _get_tool("find_todos")
    with patch("codebase_mcp.server.get_all_repos", return_value={}):
        result = fn()
    assert "No repos" in result


def test_find_todos_finds_comment(tmp_path):
    src = tmp_path / "app.py"
    src.write_text("x = 1  # TODO: fix this\ny = 2\n# FIXME broken\n")
    fn = _get_tool("find_todos")
    with patch(
        "codebase_mcp.server.get_all_repos",
        return_value={
            str(tmp_path): {
                "repo_id": "abc",
                "last_indexed": "2024-01-01T00:00:00Z",
                "chunk_count": 1,
            }
        },
    ):
        result = fn(repo_path=str(tmp_path))
    assert "TODO" in result or "FIXME" in result


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
    with (
        patch(
            "codebase_mcp.server.get_all_repos",
            return_value={
                str(tmp_path): {"repo_id": "abc", "last_indexed": past_time, "chunk_count": 1}
            },
        ),
        patch("codebase_mcp.indexer.iter_files", return_value=[src]),
    ):
        result = fn(repo_path=str(tmp_path))
    assert "app.py" in result


def test_add_decision_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEBASE_MCP_DATA_DIR", str(tmp_path))
    fn = _get_tool("add_decision")
    result = fn(
        title="Use SQLite", body="SQLite for knowledge persistence", category="architecture"
    )
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
    with (
        patch(
            "codebase_mcp.server.get_all_repos",
            return_value={
                "/some/repo": {
                    "repo_id": "abc",
                    "last_indexed": "2000-01-01T00:00:00+00:00",
                    "chunk_count": 42,
                }
            },
        ),
        patch("codebase_mcp.indexer.iter_files", return_value=[]),
    ):
        result = fn()
    assert "SQLite" in result
    assert "42" in result
