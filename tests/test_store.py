import json
import os
import pytest
from pathlib import Path


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEBASE_MCP_DATA_DIR", str(tmp_path))
    return tmp_path


def test_get_repo_id_is_stable():
    from codebase_mcp.store import get_repo_id
    assert get_repo_id("/some/path") == get_repo_id("/some/path")
    assert get_repo_id("/some/path") != get_repo_id("/other/path")


def test_config_roundtrip(tmp_path):
    from codebase_mcp.store import add_repo, load_config, is_indexed
    path = str(tmp_path / "myrepo")
    assert not is_indexed(path)
    add_repo(path, chunk_count=42)
    assert is_indexed(path)
    config = load_config()
    assert path in config
    assert config[path]["chunk_count"] == 42


def test_remove_repo(tmp_path):
    from codebase_mcp.store import add_repo, remove_repo, is_indexed
    path = str(tmp_path / "myrepo")
    add_repo(path, chunk_count=10)
    assert is_indexed(path)
    remove_repo(path)
    assert not is_indexed(path)


def test_get_all_repos(tmp_path):
    from codebase_mcp.store import add_repo, get_all_repos
    p1 = str(tmp_path / "repo1")
    p2 = str(tmp_path / "repo2")
    add_repo(p1, chunk_count=5)
    add_repo(p2, chunk_count=15)
    repos = get_all_repos()
    assert p1 in repos
    assert p2 in repos


def test_ensure_collection_creates_new(tmp_path):
    from codebase_mcp.store import ensure_collection, get_client, get_repo_id
    client = get_client()
    repo_id = get_repo_id(str(tmp_path / "repo"))
    ensure_collection(client, repo_id)
    assert client.collection_exists(repo_id)


def test_ensure_collection_replaces_existing(tmp_path):
    from codebase_mcp.store import ensure_collection, get_client, get_repo_id
    from qdrant_client.models import PointStruct
    client = get_client()
    repo_id = get_repo_id(str(tmp_path / "repo"))
    # Create with a point
    ensure_collection(client, repo_id)
    client.upsert(
        collection_name=repo_id,
        points=[PointStruct(id=0, vector=[0.1] * 1536, payload={"x": 1})],
    )
    # Re-create — old point must be gone
    ensure_collection(client, repo_id)
    results = client.scroll(collection_name=repo_id, limit=10)[0]
    assert len(results) == 0
