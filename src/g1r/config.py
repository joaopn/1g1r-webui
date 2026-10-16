"""Configuration: packaged defaults, deep-merged with the user's config.yaml, validated.

Unknown keys are rejected so a typo in config.yaml fails loudly instead of being ignored.
"""

import os
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    library_file: str
    # The built web app (index.html + assets/); nothing is served when it is missing.
    web_dist: Path
    roms_root: Path
    discarded_dirname: str
    extra_mounts_root: Path

    @property
    def database_path(self) -> Path:
        return self.data_dir / self.database_file

    @property
    def library_path(self) -> Path:
        return self.data_dir / self.library_file

    @property
    def discarded_root(self) -> Path:
        return self.roms_root / self.discarded_dirname


class DatabaseConfig(_Strict):
    busy_timeout_ms: int = Field(ge=0)


class ColumnSize(_Strict):
    rem: float = Field(gt=0)
    min: float = Field(gt=0)
    max: float = Field(gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> "ColumnSize":
        if not self.min <= self.rem <= self.max:
            raise ValueError("a column size needs min <= rem <= max")
        return self


class SidebarConfig(_Strict):
    width_rem: float = Field(gt=0)
    min_rem: float = Field(gt=0)
    max_rem: float = Field(gt=0)


class UiConfig(_Strict):
    page_size: int = Field(gt=0)
    poll_interval_ms: int = Field(gt=0)
    hash_display_length: int = Field(gt=0)
    byte_unit_base: int = Field(gt=1)
    byte_units: list[str] = Field(min_length=1)
    sidebar: SidebarConfig
    platform_icon_width_rem: float = Field(gt=0)
    resize_step_rem: float = Field(gt=0)
    resize_shift_multiplier: float = Field(gt=0)
    rem_fallback_px: float = Field(gt=0)
    game_columns: dict[str, ColumnSize]
    game_columns_default: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _known_defaults(self) -> "UiConfig":
        unknown = [c for c in self.game_columns_default if c not in self.game_columns]
        if unknown:
            raise ValueError(f"ui.game_columns_default names unknown columns {unknown}")
        return self


class FoldersConfig(_Strict):
    label_pattern: str


# The container name for a bare, unarchived ROM file.
PLAIN = "plain"


class TargetConfig(_Strict):
    label: str
    description: str
    produces: str
    accepts: list[str]

    @model_validator(mode="after")
    def _produces_is_accepted(self) -> "TargetConfig":
        if self.produces not in self.accepts:
            raise ValueError(f"a target must accept what it produces ({self.produces})")
        return self


PLATFORM_KINDS = ("console", "handheld")


class PlatformProfile(_Strict):
    name: str
    # The platform's icon: a short label in a chip, and the kind of device it is.
    short: str = Field(min_length=1)
    kind: str
    nointro_dat: str
    rom_extensions: list[str] = Field(min_length=1)
    targets: list[str] = Field(min_length=1)
    default_target: str


class PlatformsConfig(_Strict):
    enabled: list[str]
    archive_extensions: list[str]
    targets: dict[str, TargetConfig]
    profiles: dict[str, PlatformProfile]

    @model_validator(mode="after")
    def _consistent(self) -> "PlatformsConfig":
        missing = [p for p in self.enabled if p not in self.profiles]
        if missing:
            raise ValueError(f"platforms.enabled lists platforms without a profile: {missing}")
        containers = {*self.archive_extensions, PLAIN}
        for target_id, target in self.targets.items():
            unknown = [c for c in target.accepts if c not in containers]
            if unknown:
                raise ValueError(f"target {target_id}: unknown containers {unknown}")
        for platform_id, profile in self.profiles.items():
            unknown = [t for t in profile.targets if t not in self.targets]
            if unknown:
                raise ValueError(f"platform {platform_id}: unknown targets {unknown}")
            if profile.default_target not in profile.targets:
                raise ValueError(f"platform {platform_id}: default_target not in its targets")
            if profile.kind not in PLATFORM_KINDS:
                raise ValueError(f"platform {platform_id}: kind must be one of {PLATFORM_KINDS}")
        return self

    def enabled_profiles(self) -> dict[str, PlatformProfile]:
        return {p: self.profiles[p] for p in self.enabled}


class DatSourceConfig(_Strict):
    label: str
    identification_only: bool
    url_template: str | None = None
    website: str | None = None


class DatsConfig(_Strict):
    directory: str
    sources: dict[str, DatSourceConfig]
    download_timeout_seconds: float = Field(gt=0)
    max_upload_bytes: int = Field(gt=0)
    user_agent: str
    auto_activate_new: bool

    @model_validator(mode="after")
    def _known_sources(self) -> "DatsConfig":
        required = {"libretro", "nointro", "upload"}
        if not required <= set(self.sources):
            raise ValueError(f"dats.sources must define {sorted(required)}")
        if not self.sources["libretro"].url_template:
            raise ValueError("dats.sources.libretro.url_template is required")
        return self


class IgirConfig(_Strict):
    binary: str
    cache_file: str
    work_dir: str
    timeout_seconds: float = Field(gt=0)


class ArchivesConfig(_Strict):
    seven_zip_binary: str
    list_timeout_seconds: float = Field(gt=0)


class JobsConfig(_Strict):
    workers: int = Field(gt=0)


class HeaderRule(_Strict):
    header_size: int = Field(gt=0)
    magic_hex: str | None = None
    magic_offset: int = Field(default=0, ge=0)
    size_modulus: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _has_a_test(self) -> "HeaderRule":
        if self.magic_hex is None and self.size_modulus is None:
            raise ValueError("a header rule needs magic_hex or size_modulus")
        if self.magic_hex is not None:
            bytes.fromhex(self.magic_hex)
        return self


class NamesConfig(_Strict):
    regions: list[str]
    prerelease_tags: list[str]
    rerelease_tags: list[str]
    neutral_tags: list[str]


class GroupingConfig(_Strict):
    infer_from_dat_names: bool
    retool_clonelists_dir: Path


RANKING_CRITERIA = ("prerelease", "region", "language", "revision", "original")


class RankingConfig(_Strict):
    criteria: list[str]
    regions: list[str]
    languages: list[str]
    multi_region: str

    @model_validator(mode="after")
    def _valid(self) -> "RankingConfig":
        unknown = [c for c in self.criteria if c not in RANKING_CRITERIA]
        if unknown:
            raise ValueError(f"unknown ranking criteria {unknown}; use {list(RANKING_CRITERIA)}")
        if len(set(self.criteria)) != len(self.criteria):
            raise ValueError("a ranking criterion is listed twice")
        if self.multi_region not in ("best", "first"):
            raise ValueError("ranking.multi_region must be 'best' or 'first'")
        return self


class Settings(_Strict):
    app: AppConfig
    server: ServerConfig
    paths: PathsConfig
    database: DatabaseConfig
    ui: UiConfig
    folders: FoldersConfig
    ignored_filenames: list[str]
    platforms: PlatformsConfig
    dats: DatsConfig
    igir: IgirConfig
    archives: ArchivesConfig
    jobs: JobsConfig
    headers: dict[str, list[HeaderRule]]
    names: NamesConfig
    grouping: GroupingConfig
    ranking: RankingConfig

    @property
    def dats_root(self) -> Path:
        return self.paths.data_dir / self.dats.directory


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
