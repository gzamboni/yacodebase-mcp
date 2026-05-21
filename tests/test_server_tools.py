import asyncio

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
