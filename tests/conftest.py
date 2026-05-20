from pathlib import Path

import pytest


@pytest.fixture
def fixture_repo(tmp_path) -> Path:
    """Minimal repo with known content for integration tests."""
    repo = tmp_path / "fixture_repo"
    repo.mkdir()
    (repo / "auth.py").write_text(
        "def authenticate(token: str) -> bool:\n"
        "    # Verify JWT token\n"
        "    return token.startswith('Bearer ')\n"
    )
    (repo / "utils.py").write_text(
        "def format_date(dt) -> str:\n    return dt.strftime('%Y-%m-%d')\n"
    )
    (repo / "README.md").write_text("# Fixture Repo\n\nUsed for testing.\n")
    return repo
