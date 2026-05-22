import json
from pathlib import Path

import pytest


@pytest.fixture
def agent_config_dir(tmp_path, monkeypatch):
    """Patch Path.home so all agent config paths point into tmp_path."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


def test_claude_code_config_path(agent_config_dir):
    from codebase_mcp.agents import AGENTS

    expected = agent_config_dir / ".claude" / "settings.json"
    assert AGENTS["claude-code"].config_path() == expected


def test_install_creates_config(agent_config_dir):
    from codebase_mcp.agents import AGENTS, MCP_SERVER_NAME, install_agent

    agent = AGENTS["claude-code"]
    result = install_agent(agent)
    assert result == "installed"
    data = json.loads(agent.config_path().read_text())
    assert MCP_SERVER_NAME in data["mcpServers"]
    assert data["mcpServers"][MCP_SERVER_NAME]["command"] == "yacodebase-mcp"
    assert data["mcpServers"][MCP_SERVER_NAME]["args"] == ["serve"]


def test_install_idempotent(agent_config_dir):
    from codebase_mcp.agents import AGENTS, install_agent

    agent = AGENTS["claude-code"]
    install_agent(agent)
    result = install_agent(agent)
    assert result == "already"


def test_install_dry_run_no_write(agent_config_dir):
    from codebase_mcp.agents import AGENTS, install_agent

    agent = AGENTS["claude-code"]
    result = install_agent(agent, dry_run=True)
    assert result == "dry_run"
    assert not agent.config_path().exists()


def test_install_merges_existing_config(agent_config_dir):
    from codebase_mcp.agents import AGENTS, MCP_SERVER_NAME, install_agent

    agent = AGENTS["claude-code"]
    agent.config_path().parent.mkdir(parents=True, exist_ok=True)
    agent.config_path().write_text(json.dumps({"other_setting": True}))

    install_agent(agent)
    data = json.loads(agent.config_path().read_text())
    assert data["other_setting"] is True
    assert MCP_SERVER_NAME in data["mcpServers"]


def test_vscode_format(agent_config_dir):
    from codebase_mcp.agents import AGENTS, MCP_SERVER_NAME, install_agent

    agent = AGENTS["copilot"]
    install_agent(agent)
    data = json.loads(agent.config_path().read_text())
    entry = data["mcp"]["servers"][MCP_SERVER_NAME]
    assert entry["type"] == "stdio"
    assert entry["command"] == "yacodebase-mcp"


def test_zed_format(agent_config_dir):
    from codebase_mcp.agents import AGENTS, MCP_SERVER_NAME, install_agent

    agent = AGENTS["zed"]
    install_agent(agent)
    data = json.loads(agent.config_path().read_text())
    entry = data["context_servers"][MCP_SERVER_NAME]
    assert entry["command"]["path"] == "yacodebase-mcp"
    assert entry["command"]["args"] == ["serve"]


def test_is_installed_false_when_absent(agent_config_dir):
    from codebase_mcp.agents import AGENTS

    assert AGENTS["claude-code"].is_installed() is False


def test_is_installed_true_after_install(agent_config_dir):
    from codebase_mcp.agents import AGENTS, install_agent

    agent = AGENTS["cursor"]
    install_agent(agent)
    assert agent.is_installed() is True


def test_all_agents_present():
    from codebase_mcp.agents import AGENTS

    expected = {"claude-code", "cursor", "windsurf", "copilot", "zed", "opencode"}
    assert set(AGENTS.keys()) == expected
