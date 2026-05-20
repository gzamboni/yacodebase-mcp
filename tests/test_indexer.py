import pytest
from pathlib import Path
import os
from unittest.mock import MagicMock, patch


@pytest.fixture
def fixture_repo(tmp_path):
    """Small repo with known files for deterministic testing."""
    (tmp_path / "main.py").write_text("def hello():\n    return 'hi'\n")
    (tmp_path / "utils.py").write_text("\n".join(f"# line {i}" for i in range(150)))
    (tmp_path / "README.md").write_text("# Docs\n\nSome docs here.\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.js").write_text("should be skipped")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("should be skipped")
    (tmp_path / "binary.bin").write_bytes(b"\x00\x01\x02")
    return tmp_path


def test_iter_files_skips_hidden_dirs(fixture_repo):
    from codebase_mcp.indexer import iter_files
    files = list(iter_files(fixture_repo))
    paths = [str(f) for f in files]
    assert not any("node_modules" in p for p in paths)
    assert not any(".git" in p for p in paths)
    assert not any(".bin" in p for p in paths)


def test_iter_files_finds_source_files(fixture_repo):
    from codebase_mcp.indexer import iter_files
    names = {f.name for f in iter_files(fixture_repo)}
    assert "main.py" in names
    assert "utils.py" in names
    assert "README.md" in names


def test_chunk_file_short_file_single_chunk():
    from codebase_mcp.indexer import _chunk_file_lines
    content = "\n".join(f"line {i}" for i in range(10))
    chunks = _chunk_file_lines(content, "short.py", "/repo")
    assert len(chunks) == 1
    assert chunks[0]["start_line"] == 1
    assert chunks[0]["file"] == "short.py"
    assert chunks[0]["repo_path"] == "/repo"


def test_chunk_file_long_file_multiple_chunks():
    from codebase_mcp.indexer import _chunk_file_lines
    content = "\n".join(f"line {i}" for i in range(200))
    chunks = _chunk_file_lines(content, "long.py", "/repo")
    assert len(chunks) > 1
    # chunks overlap: second chunk starts before first ends
    assert chunks[1]["start_line"] < chunks[0]["end_line"]


def test_chunk_file_overlap():
    from codebase_mcp.indexer import _chunk_file_lines, CHUNK_LINES, OVERLAP_LINES
    content = "\n".join(f"line {i}" for i in range(CHUNK_LINES * 2))
    chunks = _chunk_file_lines(content, "f.py", "/r")
    step = CHUNK_LINES - OVERLAP_LINES
    assert chunks[1]["start_line"] == step + 1


@pytest.fixture(autouse=True)
def isolated_store(tmp_path_factory, monkeypatch):
    # Use a separate tmp_path for the store to avoid conflicts with fixture_repo
    store_dir = tmp_path_factory.mktemp("codebase_mcp_store")
    monkeypatch.setenv("CODEBASE_MCP_DATA_DIR", str(store_dir))


def _fake_embedding(size: int = 1536) -> list[float]:
    return [0.1] * size


def _mock_openai():
    """Create a mock OpenAI client that returns embeddings based on input size."""
    mock = MagicMock()

    def create_embeddings(model, input):
        # Return one embedding per input text
        num_texts = len(input) if isinstance(input, list) else 1
        return MagicMock(data=[
            MagicMock(embedding=_fake_embedding()) for _ in range(num_texts)
        ])

    mock.embeddings.create.side_effect = create_embeddings
    return mock


def test_index_repo_returns_chunk_count(fixture_repo):
    from codebase_mcp.indexer import index_repo, iter_files, chunk_file

    # Count expected chunks
    chunks = []
    for f in iter_files(fixture_repo):
        content = f.read_text(encoding="utf-8", errors="ignore")
        chunks.extend(chunk_file(content, str(f), str(fixture_repo)))
    expected = len(chunks)

    with patch("codebase_mcp.indexer.OpenAI") as MockOpenAI:
        MockOpenAI.return_value = _mock_openai()
        count = index_repo(str(fixture_repo))

    assert count == expected


def test_index_repo_saves_to_config(fixture_repo):
    from codebase_mcp.indexer import index_repo
    from codebase_mcp.store import is_indexed

    with patch("codebase_mcp.indexer.OpenAI") as MockOpenAI:
        MockOpenAI.return_value = _mock_openai()
        index_repo(str(fixture_repo))

    assert is_indexed(str(fixture_repo.resolve()))


def test_index_repo_replaces_existing(fixture_repo):
    from codebase_mcp.indexer import index_repo
    from codebase_mcp.store import get_client, get_repo_id, load_config

    with patch("codebase_mcp.indexer.OpenAI") as MockOpenAI:
        MockOpenAI.return_value = _mock_openai()
        first_count = index_repo(str(fixture_repo))
        second_count = index_repo(str(fixture_repo))

    assert first_count == second_count

    # Verify collection was replaced, not doubled
    abs_path = str(fixture_repo.resolve())
    repo_id = get_repo_id(abs_path)
    client = get_client()
    results = client.scroll(collection_name=repo_id, limit=1000)[0]
    assert len(results) == second_count

    config = load_config()
    assert abs_path in config


def test_chunk_file_uses_ast_for_python():
    from codebase_mcp.indexer import chunk_file
    content = "def hello():\n    return 'hi'\n"
    chunks = chunk_file(content, "hello.py", "/repo")
    assert len(chunks) == 1
    assert "node_type" in chunks[0]
    assert chunks[0]["node_type"] == "function_definition"
