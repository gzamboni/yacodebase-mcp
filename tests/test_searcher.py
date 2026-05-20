from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEBASE_MCP_DATA_DIR", str(tmp_path))


def _fake_embedding(size: int = 1536) -> list[float]:
    return [0.1] * size


def _mock_openai():
    mock = MagicMock()
    mock.embeddings.create.return_value.data = [MagicMock(embedding=_fake_embedding())]
    return mock


def _seeded_store(tmp_path, repo_path: str):
    """Put a fake repo entry in config + a real Qdrant collection with one point."""
    from qdrant_client.models import PointStruct

    from codebase_mcp.store import add_repo, ensure_collection, get_client, get_repo_id

    abs_path = str(Path(repo_path).resolve())
    repo_id = get_repo_id(abs_path)
    add_repo(abs_path, chunk_count=1)
    client = get_client()
    ensure_collection(client, repo_id)
    client.upsert(
        collection_name=repo_id,
        points=[
            PointStruct(
                id=0,
                vector=_fake_embedding(),
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


def test_search_returns_results(tmp_path):
    abs_path = _seeded_store(tmp_path, str(tmp_path / "myrepo"))

    with patch("codebase_mcp.searcher.OpenAI") as MockOpenAI:
        MockOpenAI.return_value = _mock_openai()
        from codebase_mcp.searcher import search

        result = search("something", repo_path=abs_path)

    assert "main.py" in result
    assert "lines 1-5" in result


def test_search_all_repos_when_no_path(tmp_path):
    _seeded_store(tmp_path, str(tmp_path / "myrepo"))

    with patch("codebase_mcp.searcher.OpenAI") as MockOpenAI:
        MockOpenAI.return_value = _mock_openai()
        from codebase_mcp.searcher import search

        result = search("something")

    assert "main.py" in result


def test_search_not_indexed_repo(tmp_path):
    with patch("codebase_mcp.searcher.OpenAI") as MockOpenAI:
        MockOpenAI.return_value = _mock_openai()
        from codebase_mcp.searcher import search

        result = search("something", repo_path=str(tmp_path / "nonexistent"))

    assert "not indexed" in result.lower()


def test_search_no_repos_indexed(tmp_path):
    with patch("codebase_mcp.searcher.OpenAI") as MockOpenAI:
        MockOpenAI.return_value = _mock_openai()
        from codebase_mcp.searcher import search

        result = search("something")

    assert "no repos" in result.lower()
