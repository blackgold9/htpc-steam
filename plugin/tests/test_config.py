import json
import stat

import pytest
from uc_steamos_agent.config import AgentConfig, load_config, save_config


def test_load_config_creates_defaults(tmp_path):
    config = load_config(str(tmp_path), version="0.1.0")
    assert config.version == "0.1.0"
    assert config.port == 8086
    assert config.host == "0.0.0.0"
    assert config.auth_token == ""
    assert config.wol_arm is False
    assert (tmp_path / "config.json").exists()
    assert stat.S_IMODE((tmp_path / "config.json").stat().st_mode) == 0o600


def test_load_config_reads_persisted_overrides(tmp_path):
    save_config(
        str(tmp_path),
        AgentConfig(version="0.1.0", host="127.0.0.1", port=9001, auth_token="secret", wol_arm=True),
    )
    config = load_config(str(tmp_path), version="0.2.0")
    assert config.version == "0.2.0"
    assert config.host == "127.0.0.1"
    assert config.port == 9001
    assert config.auth_token == "secret"
    assert config.wol_arm is True
    assert stat.S_IMODE((tmp_path / "config.json").stat().st_mode) == 0o600


def test_load_config_ignores_retired_settings_without_rewriting_existing_file(tmp_path):
    path = tmp_path / "config.json"
    original = json.dumps({
        "host": "127.0.0.1",
        "port": 9001,
        "auth_token": "http-secret",
        "wol_arm": True,
        "agent_id": "a" * 32,
        "mqtt": {"enabled": True, "host": "ha.internal", "password": "old-secret"},
    })
    path.write_text(original)

    config = load_config(str(tmp_path), version="0.1.0")

    assert config == AgentConfig(
        version="0.1.0", host="127.0.0.1", port=9001, auth_token="http-secret", wol_arm=True,
    )
    assert path.read_text() == original

    save_config(str(tmp_path), config)
    assert json.loads(path.read_text()) == {
        "host": "127.0.0.1", "port": 9001, "auth_token": "http-secret", "wol_arm": True,
    }


def test_save_config_failure_preserves_previous_file_and_cleans_temporary_file(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    original = '{"auth_token": "original-secret"}'
    path.write_text(original)

    def fail_replace(*args):
        raise OSError("replace failed")

    monkeypatch.setattr("uc_steamos_agent.config.os.replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        save_config(str(tmp_path), AgentConfig(auth_token="replacement-secret"))

    assert path.read_text() == original
    assert list(tmp_path.iterdir()) == [path]


def test_load_config_survives_corrupt_file(tmp_path):
    (tmp_path / "config.json").write_text("not json")
    config = load_config(str(tmp_path), version="0.1.0")
    assert config.port == 8086


def test_load_config_survives_non_utf8_file(tmp_path):
    (tmp_path / "config.json").write_bytes(b'{"auth_token":"\xff"}')

    config = load_config(str(tmp_path), version="0.1.0")

    assert config == AgentConfig(version="0.1.0")
