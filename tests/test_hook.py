import stat
from pathlib import Path

import pytest


@pytest.fixture
def git_repo(tmp_path):
    (tmp_path / ".git" / "hooks").mkdir(parents=True)
    return tmp_path


def test_install_creates_hook(git_repo):
    from codebase_mcp.hook import MARKER, install_hook

    result = install_hook(str(git_repo))
    assert result["status"] == "installed"
    hook = git_repo / ".git" / "hooks" / "post-commit"
    assert hook.exists()
    content = hook.read_text()
    assert MARKER in content
    assert 'yacodebase-mcp update "$(git rev-parse --show-toplevel)"' in content
    assert hook.stat().st_mode & stat.S_IXUSR


def test_install_idempotent(git_repo):
    from codebase_mcp.hook import install_hook

    install_hook(str(git_repo))
    result = install_hook(str(git_repo))
    assert result["status"] == "already"


def test_install_appends_to_existing_hook(git_repo):
    from codebase_mcp.hook import MARKER, install_hook

    hook = git_repo / ".git" / "hooks" / "post-commit"
    hook.write_text("#!/bin/sh\necho hello\n")

    result = install_hook(str(git_repo))
    assert result["status"] == "appended"
    content = hook.read_text()
    assert "echo hello" in content
    assert MARKER in content


def test_install_not_git_repo(tmp_path):
    from codebase_mcp.hook import install_hook

    with pytest.raises(ValueError, match="Not a git repo"):
        install_hook(str(tmp_path))


def test_uninstall_removes_standalone_hook(git_repo):
    from codebase_mcp.hook import install_hook, uninstall_hook

    install_hook(str(git_repo))
    result = uninstall_hook(str(git_repo))
    assert result["status"] == "removed"
    assert not (git_repo / ".git" / "hooks" / "post-commit").exists()


def test_uninstall_preserves_other_hook_content(git_repo):
    from codebase_mcp.hook import MARKER, install_hook, uninstall_hook

    hook = git_repo / ".git" / "hooks" / "post-commit"
    hook.write_text("#!/bin/sh\necho hello\n")
    install_hook(str(git_repo))

    uninstall_hook(str(git_repo))
    content = hook.read_text()
    assert "echo hello" in content
    assert MARKER not in content


def test_uninstall_not_installed(git_repo):
    from codebase_mcp.hook import uninstall_hook

    result = uninstall_hook(str(git_repo))
    assert result["status"] == "not_installed"


def test_hook_status_true(git_repo):
    from codebase_mcp.hook import hook_status, install_hook

    install_hook(str(git_repo))
    assert hook_status(str(git_repo)) is True


def test_hook_status_false_no_hook(git_repo):
    from codebase_mcp.hook import hook_status

    assert hook_status(str(git_repo)) is False


def test_hook_status_false_other_hook(git_repo):
    from codebase_mcp.hook import hook_status

    hook = git_repo / ".git" / "hooks" / "post-commit"
    hook.write_text("#!/bin/sh\necho other\n")
    assert hook_status(str(git_repo)) is False
