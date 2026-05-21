import pytest

from codebase_mcp.store import load_file_hashes, save_file_hashes


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEBASE_MCP_DATA_DIR", str(tmp_path))
    return tmp_path


def test_save_and_load_file_hashes(isolated):
    from codebase_mcp.store import add_repo

    add_repo("/test/repo", 10)

    hashes = {"src/a.py": "abc123", "src/b.py": "def456"}
    save_file_hashes("/test/repo", hashes)

    loaded = load_file_hashes("/test/repo")
    assert loaded == hashes


def test_load_file_hashes_missing_repo(isolated):
    result = load_file_hashes("/nonexistent/repo")
    assert result == {}


def test_save_file_hashes_unknown_repo_is_noop(isolated):
    # Should not raise, just silently skip
    save_file_hashes("/not/indexed", {"file.py": "hash"})
    result = load_file_hashes("/not/indexed")
    assert result == {}
