import pytest

from g1r.config import DATA_DIR_ENV, ConfigError, deep_merge, load_defaults, load_settings


def test_defaults_validate(make_settings, data_dir):
    settings = make_settings()
    assert settings.paths.data_dir == data_dir
    assert settings.paths.database_path == data_dir / "state.db"
    assert settings.paths.discarded_root == settings.paths.roms_root / "discarded"


def test_user_override_is_deep_merged(make_settings):
    settings = make_settings(
        {"ui": {"page_size": 25}, "app": {"source_url": "https://example.org/src"}}
    )
    assert settings.ui.page_size == 25
    assert settings.app.source_url == "https://example.org/src"
    assert settings.server.port == load_defaults()["server"]["port"]


def test_unknown_key_is_rejected(make_settings):
    with pytest.raises(ConfigError, match="pagesize"):
        make_settings({"ui": {"pagesize": 25}})


def test_invalid_value_is_rejected(make_settings):
    with pytest.raises(ConfigError):
        make_settings({"server": {"port": 0}})


def test_non_mapping_config_is_rejected(data_dir):
    data_dir.mkdir(parents=True)
    (data_dir / "config.yaml").write_text("- just a list\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="mapping"):
        load_settings({DATA_DIR_ENV: str(data_dir)})


def test_enabled_platform_needs_profile(make_settings):
    with pytest.raises(ConfigError, match="without a profile"):
        make_settings({"platforms": {"enabled": ["nes", "psx"]}})


def test_default_target_must_be_allowed(make_settings):
    with pytest.raises(ConfigError, match="default_target"):
        make_settings({"platforms": {"profiles": {"nes": {"default_target": "chd"}}}})


def test_wave_one_platforms_are_enabled(make_settings):
    enabled = make_settings().platforms.enabled
    assert {"nes", "gb", "snes", "genesis"} <= set(enabled)
    assert not {"psx", "psvita", "wii"} & set(enabled)


def test_deep_merge_replaces_non_mappings():
    assert deep_merge({"a": {"b": 1, "c": [1]}}, {"a": {"c": [2]}}) == {"a": {"b": 1, "c": [2]}}
