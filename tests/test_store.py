import pytest


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("YACODEBASE_MCP_DATA_DIR", str(tmp_path))
    return tmp_path


def test_get_repo_id_is_stable():
    from yacodebase_mcp.store import get_repo_id

    assert get_repo_id("/some/path") == get_repo_id("/some/path")
    assert get_repo_id("/some/path") != get_repo_id("/other/path")


def test_repo_key_is_branch_qualified_for_git_repos(tmp_path):
    import subprocess

    from yacodebase_mcp.store import repo_key

    repo = tmp_path / "gitrepo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "main"], check=True)
    key_main = repo_key(str(repo))
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "feature"], check=True)
    key_feature = repo_key(str(repo))

    assert key_main == f"{repo}#main"
    assert key_feature == f"{repo}#feature"
    assert key_main != key_feature


def test_repo_key_falls_back_to_path_for_non_git_dirs(tmp_path):
    from yacodebase_mcp.store import repo_key

    plain = tmp_path / "plain"
    plain.mkdir()
    assert repo_key(str(plain)) == str(plain)


def test_add_repo_isolates_index_per_branch(tmp_path):
    import subprocess

    from yacodebase_mcp.store import add_repo, get_all_repos, is_indexed

    repo = tmp_path / "gitrepo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "main"], check=True)
    add_repo(str(repo), chunk_count=1)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "feature"], check=True)

    assert not is_indexed(str(repo))
    add_repo(str(repo), chunk_count=2)
    assert is_indexed(str(repo))

    repos = get_all_repos()
    assert len(repos) == 2
    branches = {meta["branch"] for meta in repos.values()}
    assert branches == {"main", "feature"}


def test_config_roundtrip(tmp_path):
    from yacodebase_mcp.store import add_repo, is_indexed, load_config

    path = str(tmp_path / "myrepo")
    assert not is_indexed(path)
    add_repo(path, chunk_count=42)
    assert is_indexed(path)
    config = load_config()
    assert path in config
    assert config[path]["chunk_count"] == 42


def test_remove_repo(tmp_path):
    from yacodebase_mcp.store import add_repo, is_indexed, remove_repo

    path = str(tmp_path / "myrepo")
    add_repo(path, chunk_count=10)
    assert is_indexed(path)
    remove_repo(path)
    assert not is_indexed(path)


def test_get_all_repos(tmp_path):
    from yacodebase_mcp.store import add_repo, get_all_repos

    p1 = str(tmp_path / "repo1")
    p2 = str(tmp_path / "repo2")
    add_repo(p1, chunk_count=5)
    add_repo(p2, chunk_count=15)
    repos = get_all_repos()
    assert p1 in repos
    assert p2 in repos


def test_get_client_uses_local_path_by_default(tmp_path):
    from yacodebase_mcp.store import _qdrant_path, get_client

    client = get_client()
    assert not client.collection_exists("nonexistent-collection")
    assert _qdrant_path().exists()


def test_get_client_uses_remote_url_when_configured(tmp_path, monkeypatch):
    import yacodebase_mcp.store as store_mod
    from yacodebase_mcp.settings import Settings, save_settings

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


def test_ensure_collection_creates_new(tmp_path):
    from yacodebase_mcp.store import ensure_collection, get_client, get_repo_id

    client = get_client()
    repo_id = get_repo_id(str(tmp_path / "repo"))
    ensure_collection(client, repo_id, vector_size=1536)
    assert client.collection_exists(repo_id)


def test_ensure_collection_replaces_existing(tmp_path):
    from qdrant_client.models import PointStruct

    from yacodebase_mcp.store import ensure_collection, get_client, get_repo_id

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


def test_data_dir_migrates_old_to_new(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.delenv("YACODEBASE_MCP_DATA_DIR", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    old = tmp_path / ".codebase-mcp"
    old.mkdir()
    (old / "config.json").write_text("{}")

    from yacodebase_mcp.store import _data_dir

    result = _data_dir()
    assert result == tmp_path / ".yacodebase-mcp"
    assert (result / "config.json").exists()
    assert not old.exists()


def test_data_dir_no_old_dir(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.delenv("YACODEBASE_MCP_DATA_DIR", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    from yacodebase_mcp.store import _data_dir

    result = _data_dir()
    assert result == tmp_path / ".yacodebase-mcp"


def test_data_dir_env_var_wins(tmp_path, monkeypatch):
    from pathlib import Path

    custom = str(tmp_path / "custom-data")
    monkeypatch.setenv("YACODEBASE_MCP_DATA_DIR", custom)

    from yacodebase_mcp.store import _data_dir

    assert _data_dir() == Path(custom)
