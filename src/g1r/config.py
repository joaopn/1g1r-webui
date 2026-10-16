"""Configuration: packaged defaults, deep-merged with the user's config.yaml, validated.

Unknown keys are rejected so a typo in config.yaml fails loudly instead of being ignored.
"""

import os
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

# The one value needed before any config file can be read: where the data directory is.
DATA_DIR_ENV = "G1R_DATA_DIR"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AppConfig(_Strict):
    name: str
    source_url: str


class ServerConfig(_Strict):
    host: str
    port: int = Field(gt=0)


class PathsConfig(_Strict):
    data_dir: Path
    database_file: str
    user_config_file: str
    roms_root: Path
    discarded_dirname: str
    extra_mounts_root: Path

    @property
    def database_path(self) -> Path:
        return self.data_dir / self.database_file

    @property
    def discarded_root(self) -> Path:
        return self.roms_root / self.discarded_dirname


class DatabaseConfig(_Strict):
    busy_timeout_ms: int = Field(ge=0)


class UiConfig(_Strict):
    page_size: int = Field(gt=0)


class Settings(_Strict):
    app: AppConfig
    server: ServerConfig
    paths: PathsConfig
    database: DatabaseConfig
    ui: UiConfig


class ConfigError(ValueError):
    """The merged configuration is not valid."""


def load_defaults() -> dict[str, Any]:
    text = resources.files("g1r").joinpath("defaults.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Return base with override applied; nested mappings merge, everything else replaces."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def user_config_path(defaults: dict[str, Any], environ: dict[str, str] | None = None) -> Path:
    environ = os.environ if environ is None else environ
    data_dir = Path(environ.get(DATA_DIR_ENV, defaults["paths"]["data_dir"]))
    return data_dir / defaults["paths"]["user_config_file"]


def load_settings(environ: dict[str, str] | None = None) -> Settings:
    environ = os.environ if environ is None else environ
    defaults = load_defaults()
    raw = defaults
    path = user_config_path(defaults, environ)
    if path.is_file():
        override = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(override, dict):
            raise ConfigError(f"{path}: the top level must be a mapping")
        raw = deep_merge(defaults, override)
    if DATA_DIR_ENV in environ:
        raw = deep_merge(raw, {"paths": {"data_dir": environ[DATA_DIR_ENV]}})
    try:
        return Settings.model_validate(raw)
    except ValueError as exc:
        raise ConfigError(f"invalid configuration ({path}): {exc}") from exc
