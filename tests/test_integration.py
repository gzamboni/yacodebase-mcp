from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEBASE_MCP_DATA_DIR", str(tmp_path))


def _fake_embedding(size: int = 1536) -> list[float]:
    return [0.1] * size


def _mock_openai_for_index():
    mock = MagicMock()
    mock.embeddings.create.side_effect = lambda model, input: MagicMock(
        data=[MagicMock(embedding=_fake_embedding()) for _ in input]
    )
    return mock


def _mock_openai_for_search():
    mock = MagicMock()
    mock.embeddings.create.return_value.data = [MagicMock(embedding=_fake_embedding())]
    return mock


def test_index_and_search(fixture_repo, tmp_path):
    """Full flow: index a repo, search it, get non-empty results."""
    from codebase_mcp.indexer import index_repo
    from codebase_mcp.searcher import search

    with patch("codebase_mcp.indexer.OpenAI") as MockIdx:
        MockIdx.return_value = _mock_openai_for_index()
        count = index_repo(str(fixture_repo))

    assert count > 0

    with patch("codebase_mcp.searcher.OpenAI") as MockSearch:
        MockSearch.return_value = _mock_openai_for_search()
        result = search("authentication token", repo_path=str(fixture_repo.resolve()))

    assert "auth.py" in result
    assert "lines" in result


def test_reindex_clears_old(fixture_repo, tmp_path):
    """Reindex replaces old chunks; chunk count stays consistent."""
    from codebase_mcp.indexer import index_repo
    from codebase_mcp.store import load_config

    with patch("codebase_mcp.indexer.OpenAI") as MockIdx:
        MockIdx.return_value = _mock_openai_for_index()
        first_count = index_repo(str(fixture_repo))
        second_count = index_repo(str(fixture_repo))

    assert first_count == second_count
    config = load_config()
    abs_path = str(fixture_repo.resolve())
    assert config[abs_path]["chunk_count"] == second_count


def test_search_no_index(tmp_path):
    """Searching an unindexed repo returns a helpful error message."""
    from codebase_mcp.searcher import search

    with patch("codebase_mcp.searcher.OpenAI") as MockSearch:
        MockSearch.return_value = _mock_openai_for_search()
        result = search("anything", repo_path=str(tmp_path / "nonexistent"))

    assert "not indexed" in result.lower()
    assert "codebase-mcp index" in result
