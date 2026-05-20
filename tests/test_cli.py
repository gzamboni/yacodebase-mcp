from unittest.mock import patch

import pytest
from click.testing import CliRunner


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEBASE_MCP_DATA_DIR", str(tmp_path))


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
    from codebase_mcp.cli import main

    with patch("codebase_mcp.indexer.OpenAI") as MockOpenAI:
        mock = MockOpenAI.return_value
        mock.embeddings.create.return_value.data = []
        result = runner.invoke(main, ["index", str(sample_repo)])

    assert result.exit_code == 0
    assert "Indexed" in result.output


def test_index_twice_fails(runner, sample_repo):
    from codebase_mcp.cli import main

    with patch("codebase_mcp.indexer.OpenAI") as MockOpenAI:
        mock = MockOpenAI.return_value
        mock.embeddings.create.return_value.data = []
        runner.invoke(main, ["index", str(sample_repo)])
        result = runner.invoke(main, ["index", str(sample_repo)])

    assert result.exit_code != 0
    assert "reindex" in result.output.lower()


def test_reindex_command(runner, sample_repo):
    from codebase_mcp.cli import main

    with patch("codebase_mcp.indexer.OpenAI") as MockOpenAI:
        mock = MockOpenAI.return_value
        mock.embeddings.create.return_value.data = []
        runner.invoke(main, ["index", str(sample_repo)])
        result = runner.invoke(main, ["reindex", str(sample_repo)])

    assert result.exit_code == 0
    assert "Re-indexed" in result.output


def test_list_command_empty(runner):
    from codebase_mcp.cli import main

    result = runner.invoke(main, ["list"])
    assert result.exit_code == 0
    assert "No repos" in result.output


def test_list_command_shows_repo(runner, sample_repo):
    from codebase_mcp.cli import main

    with patch("codebase_mcp.indexer.OpenAI") as MockOpenAI:
        mock = MockOpenAI.return_value
        mock.embeddings.create.return_value.data = []
        runner.invoke(main, ["index", str(sample_repo)])
        result = runner.invoke(main, ["list"])

    assert result.exit_code == 0
    assert str(sample_repo.resolve()) in result.output


def test_remove_command(runner, sample_repo):
    from codebase_mcp.cli import main

    with patch("codebase_mcp.indexer.OpenAI") as MockOpenAI:
        mock = MockOpenAI.return_value
        mock.embeddings.create.return_value.data = []
        runner.invoke(main, ["index", str(sample_repo)])
        result = runner.invoke(main, ["remove", str(sample_repo)])

    assert result.exit_code == 0
    assert "Removed" in result.output


def test_remove_nonexistent_fails(runner, tmp_path):
    from codebase_mcp.cli import main

    result = runner.invoke(main, ["remove", str(tmp_path / "ghost")])
    assert result.exit_code != 0
