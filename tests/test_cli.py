from unittest.mock import patch

import pytest
from click.testing import CliRunner


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("YACODEBASE_MCP_DATA_DIR", str(tmp_path))


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def sample_repo(tmp_path):
    repo = tmp_path / "myrepo"
    repo.mkdir()
    (repo / "main.py").write_text("def hello(): pass\n")
    return repo


def test_index_command(runner, sample_repo):
    from yacodebase_mcp.cli import main

    with patch("yacodebase_mcp.indexer.OpenAI") as MockOpenAI:
        mock = MockOpenAI.return_value
        mock.embeddings.create.return_value.data = []
        result = runner.invoke(main, ["index", str(sample_repo)])

    assert result.exit_code == 0
    assert "Indexed" in result.output


def test_index_twice_fails(runner, sample_repo):
    from yacodebase_mcp.cli import main

    with patch("yacodebase_mcp.indexer.OpenAI") as MockOpenAI:
        mock = MockOpenAI.return_value
        mock.embeddings.create.return_value.data = []
        runner.invoke(main, ["index", str(sample_repo)])
        result = runner.invoke(main, ["index", str(sample_repo)])

    assert result.exit_code != 0
    assert "reindex" in result.output.lower()


def test_reindex_command(runner, sample_repo):
    from yacodebase_mcp.cli import main

    with patch("yacodebase_mcp.indexer.OpenAI") as MockOpenAI:
        mock = MockOpenAI.return_value
        mock.embeddings.create.return_value.data = []
        runner.invoke(main, ["index", str(sample_repo)])
        result = runner.invoke(main, ["reindex", str(sample_repo)])

    assert result.exit_code == 0
    assert "Re-indexed" in result.output


def test_list_command_empty(runner):
    from yacodebase_mcp.cli import main

    result = runner.invoke(main, ["list"])
    assert result.exit_code == 0
    assert "No repos" in result.output


def test_list_command_shows_repo(runner, sample_repo):
    from yacodebase_mcp.cli import main

    with patch("yacodebase_mcp.indexer.OpenAI") as MockOpenAI:
        mock = MockOpenAI.return_value
        mock.embeddings.create.return_value.data = []
        runner.invoke(main, ["index", str(sample_repo)])
        result = runner.invoke(main, ["list"])

    assert result.exit_code == 0
    assert str(sample_repo.resolve()) in result.output


def test_remove_command(runner, sample_repo):
    from yacodebase_mcp.cli import main

    with patch("yacodebase_mcp.indexer.OpenAI") as MockOpenAI:
        mock = MockOpenAI.return_value
        mock.embeddings.create.return_value.data = []
        runner.invoke(main, ["index", str(sample_repo)])
        result = runner.invoke(main, ["remove", str(sample_repo)])

    assert result.exit_code == 0
    assert "Removed" in result.output


def test_remove_nonexistent_fails(runner, tmp_path):
    from yacodebase_mcp.cli import main

    result = runner.invoke(main, ["remove", str(tmp_path / "ghost")])
    assert result.exit_code != 0


def test_config_list_defaults(runner):
    from yacodebase_mcp.cli import main

    result = runner.invoke(main, ["config", "list"])
    assert result.exit_code == 0
    assert "text-embedding-3-small" in result.output
    assert "1536" in result.output


def test_config_set_known_model(runner):
    from yacodebase_mcp.cli import main
    from yacodebase_mcp.settings import get_settings

    result = runner.invoke(main, ["config", "set", "embedding-model", "text-embedding-3-large"])
    assert result.exit_code == 0
    s = get_settings()
    assert s.embedding_model == "text-embedding-3-large"
    assert s.vector_size == 3072


def test_config_set_unknown_model_without_vector_size_fails(runner):
    from yacodebase_mcp.cli import main

    result = runner.invoke(main, ["config", "set", "embedding-model", "nomic-embed-text"])
    assert result.exit_code != 0
    assert "vector-size" in result.output.lower()


def test_config_set_unknown_model_with_vector_size(runner):
    from yacodebase_mcp.cli import main
    from yacodebase_mcp.settings import get_settings

    result = runner.invoke(
        main, ["config", "set", "embedding-model", "nomic-embed-text", "--vector-size", "768"]
    )
    assert result.exit_code == 0
    s = get_settings()
    assert s.embedding_model == "nomic-embed-text"
    assert s.vector_size == 768


def test_config_set_api_key(runner):
    from yacodebase_mcp.cli import main
    from yacodebase_mcp.settings import get_settings

    result = runner.invoke(main, ["config", "set", "api-key", "sk-testkey"])
    assert result.exit_code == 0
    assert get_settings().api_key == "sk-testkey"


def test_config_set_api_base(runner):
    from yacodebase_mcp.cli import main
    from yacodebase_mcp.settings import get_settings

    result = runner.invoke(main, ["config", "set", "api-base", "http://localhost:11434/v1"])
    assert result.exit_code == 0
    assert get_settings().api_base == "http://localhost:11434/v1"


def test_config_set_qdrant_url(runner):
    from yacodebase_mcp.cli import main
    from yacodebase_mcp.settings import get_settings

    result = runner.invoke(main, ["config", "set", "qdrant-url", "http://qdrant.internal:6333"])
    assert result.exit_code == 0
    assert get_settings().qdrant_url == "http://qdrant.internal:6333"


def test_config_set_qdrant_api_key(runner):
    from yacodebase_mcp.cli import main
    from yacodebase_mcp.settings import get_settings

    result = runner.invoke(main, ["config", "set", "qdrant-api-key", "qk-testkey"])
    assert result.exit_code == 0
    assert get_settings().qdrant_api_key == "qk-testkey"


def test_config_list_shows_masked_qdrant_api_key(runner):
    from yacodebase_mcp.cli import main

    runner.invoke(main, ["config", "set", "qdrant-url", "http://qdrant.internal:6333"])
    runner.invoke(main, ["config", "set", "qdrant-api-key", "qk-abcdefgh"])
    result = runner.invoke(main, ["config", "list"])
    assert result.exit_code == 0
    assert "http://qdrant.internal:6333" in result.output
    assert "qk-abcdefgh" not in result.output
    assert "qk-ab***" in result.output


def test_config_unset_qdrant_url(runner):
    from yacodebase_mcp.cli import main
    from yacodebase_mcp.settings import get_settings

    runner.invoke(main, ["config", "set", "qdrant-url", "http://qdrant.internal:6333"])
    result = runner.invoke(main, ["config", "unset", "qdrant-url"])
    assert result.exit_code == 0
    assert get_settings().qdrant_url is None


def test_config_unset_qdrant_api_key(runner):
    from yacodebase_mcp.cli import main
    from yacodebase_mcp.settings import get_settings

    runner.invoke(main, ["config", "set", "qdrant-api-key", "qk-testkey"])
    result = runner.invoke(main, ["config", "unset", "qdrant-api-key"])
    assert result.exit_code == 0
    assert get_settings().qdrant_api_key is None


def test_config_list_shows_masked_api_key(runner):
    from yacodebase_mcp.cli import main

    runner.invoke(main, ["config", "set", "api-key", "sk-abcdefgh"])
    result = runner.invoke(main, ["config", "list"])
    assert result.exit_code == 0
    assert "sk-ab" in result.output
    assert "***" in result.output
    assert "sk-abcdefgh" not in result.output


def test_config_unset_api_key(runner):
    from yacodebase_mcp.cli import main
    from yacodebase_mcp.settings import get_settings

    runner.invoke(main, ["config", "set", "api-key", "sk-testkey"])
    result = runner.invoke(main, ["config", "unset", "api-key"])
    assert result.exit_code == 0
    assert get_settings().api_key is None


def test_config_unset_embedding_model_resets_vector_size(runner):
    from yacodebase_mcp.cli import main
    from yacodebase_mcp.settings import get_settings

    runner.invoke(main, ["config", "set", "embedding-model", "text-embedding-3-large"])
    assert get_settings().vector_size == 3072

    result = runner.invoke(main, ["config", "unset", "embedding-model"])
    assert result.exit_code == 0
    s = get_settings()
    assert s.embedding_model == "text-embedding-3-small"
    assert s.vector_size == 1536
