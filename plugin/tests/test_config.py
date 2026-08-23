from uc_steamos_agent.config import AgentConfig, load_config, save_config


def test_load_config_creates_defaults(tmp_path):
    config = load_config(str(tmp_path), version="0.1.0")
    assert config.version == "0.1.0"
    assert config.port == 8086
    assert config.host == "0.0.0.0"
    assert config.auth_token == ""
    assert (tmp_path / "config.json").exists()


def test_load_config_reads_persisted_overrides(tmp_path):
    save_config(str(tmp_path), AgentConfig(version="0.1.0", port=9001, auth_token="secret"))
    config = load_config(str(tmp_path), version="0.1.0")
    assert config.port == 9001
    assert config.auth_token == "secret"


def test_load_config_survives_corrupt_file(tmp_path):
    (tmp_path / "config.json").write_text("not json")
    config = load_config(str(tmp_path), version="0.1.0")
    assert config.port == 8086
