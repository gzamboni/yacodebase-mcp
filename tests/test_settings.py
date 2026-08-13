import json

import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("YACODEBASE_MCP_DATA_DIR", str(tmp_path))


def test_get_settings_returns_defaults_when_no_file():
    from yacodebase_mcp.settings import get_settings

    s = get_settings()
    assert s.embedding_model == "text-embedding-3-small"
    assert s.vector_size == 1536
    assert s.api_key is None
    assert s.api_base is None


def test_save_and_load_round_trip():
    from yacodebase_mcp.settings import Settings, get_settings, save_settings

    original = Settings(
        embedding_model="text-embedding-3-large",
        vector_size=3072,
        api_key="sk-test",
        api_base="http://localhost:11434/v1",
    )
    save_settings(original)
    loaded = get_settings()
    assert loaded.embedding_model == "text-embedding-3-large"
    assert loaded.vector_size == 3072
    assert loaded.api_key == "sk-test"
    assert loaded.api_base == "http://localhost:11434/v1"


def test_get_settings_ignores_unknown_fields():
    from yacodebase_mcp.settings import Settings, _settings_path, get_settings, save_settings

    save_settings(Settings(embedding_model="text-embedding-3-large", vector_size=3072))
    # inject an unknown key directly into the file
    path = _settings_path()
    data = json.loads(path.read_text())
    data["mystery"] = "value"
    path.write_text(json.dumps(data))

    s = get_settings()
    assert s.embedding_model == "text-embedding-3-large"
    assert not hasattr(s, "mystery")


def test_save_settings_omits_none_fields(tmp_path):
    from yacodebase_mcp.settings import Settings, save_settings

    save_settings(Settings(api_key=None, api_base=None))
    data = json.loads((tmp_path / "settings.json").read_text())
    assert "api_key" not in data
    assert "api_base" not in data


def test_qdrant_settings_round_trip(tmp_path):
    from yacodebase_mcp.settings import Settings, load_settings, save_settings

    save_settings(Settings(qdrant_url="http://qdrant.internal:6333", qdrant_api_key="qk-test"))
    loaded = load_settings()
    assert loaded.qdrant_url == "http://qdrant.internal:6333"
    assert loaded.qdrant_api_key == "qk-test"


def test_qdrant_settings_omitted_when_none(tmp_path):
    from yacodebase_mcp.settings import Settings, save_settings

    save_settings(Settings(qdrant_url=None, qdrant_api_key=None))
    data = json.loads((tmp_path / "settings.json").read_text())
    assert "qdrant_url" not in data
    assert "qdrant_api_key" not in data


def test_known_models_table():
    from yacodebase_mcp.settings import KNOWN_MODELS

    assert KNOWN_MODELS["text-embedding-3-small"] == 1536
    assert KNOWN_MODELS["text-embedding-3-large"] == 3072
    assert KNOWN_MODELS["text-embedding-ada-002"] == 1536
