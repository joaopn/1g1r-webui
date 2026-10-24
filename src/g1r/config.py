"""Configuration: the packaged defaults, validated.

Nothing about the app is configured from a file: what a user sets is in the compose file
(mounts, port, environment) or in the web UI (kept in library.yaml). The data directory can
be moved with G1R_DATA_DIR. Unknown keys are rejected so a typo in defaults.yaml fails loudly.
"""

import os
from importlib import resources
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

# Where the data directory is (the compose file's /data mount).
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
        return Path(os.path.normpath(self.roms_root / self.discarded_dirname))


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


class NotificationsConfig(_Strict):
    limit: int = Field(gt=0)
    idle_poll_ms: int = Field(gt=0)


class UiConfig(_Strict):
    page_size: int = Field(gt=0)
    dat_search_limit: int = Field(gt=0)
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
    conversion_columns: dict[str, ColumnSize]
    conversion_columns_default: list[str] = Field(min_length=1)
    discarded_columns: dict[str, ColumnSize]
    discarded_columns_default: list[str] = Field(min_length=1)
    ignored_columns: dict[str, ColumnSize]
    ignored_columns_default: list[str] = Field(min_length=1)
    updates_columns: dict[str, ColumnSize]
    updates_columns_default: list[str] = Field(min_length=1)
    statistics_columns: dict[str, ColumnSize]
    statistics_columns_default: list[str] = Field(min_length=1)
    statistics_source_rem: float = Field(gt=0)
    statistics_source_gap_rem: float = Field(ge=0)
    missing_columns: dict[str, ColumnSize]
    missing_columns_default: list[str] = Field(min_length=1)
    percent_digits: int = Field(ge=0)
    notifications: NotificationsConfig

    @model_validator(mode="after")
    def _known_defaults(self) -> "UiConfig":
        for table in ("game", "conversion", "discarded"):
            sizes = getattr(self, f"{table}_columns")
            unknown = [c for c in getattr(self, f"{table}_columns_default") if c not in sizes]
            if unknown:
                raise ValueError(f"ui.{table}_columns_default names unknown columns {unknown}")
        return self


class FoldersConfig(_Strict):
    label_pattern: str
    # Folder names of platforms not supported yet -> the platform's name ("not supported yet").
    unsupported_names: dict[str, str] = Field(default_factory=dict)


# The container name for a bare, unarchived ROM file.
PLAIN = "plain"


class TargetConfig(_Strict):
    label: str
    description: str
    produces: str


PLATFORM_KINDS = ("console", "handheld", "arcade", "computer")


DAT_FAMILIES = ("nointro", "redump", "fbneo", "tosec")


class PlatformProfile(_Strict):
    name: str
    # The platform's icon: a short label in a chip, and the kind of device it is.
    short: str = Field(min_length=1)
    kind: str
    # The DAT's header name, and who makes it: No-Intro (cartridges) or Redump (discs).
    dat_name: str
    dat_family: str = "nointro"
    # redump.info's name for the system, for the Download button (Redump platforms).
    redump_system: str | None = None
    # Files that are only part of a game (a cue sheet and its tracks): no versions in the
    # 1G1R table until a conversion makes one file of them.
    part_extensions: list[str] = Field(default_factory=list)
    # An ISO of this platform is a CD (createcd) or a DVD (createdvd) for chdman.
    iso_mode: str = "cd"
    rom_extensions: list[str] = Field(min_length=1)
    targets: list[str] = Field(min_length=1)
    default_target: str
    # Other folder names this platform's folders go by (RomM, ES-DE, Batocera...).
    aliases: list[str] = Field(default_factory=list)
    # Encrypted card images can be decrypted with keys the user adds (3DS: `decryption`).
    decrypts: bool = False
    # A card image header the scan reads (a key of `card_images`), or None.
    card_image: str | None = None
    # Arcade: each archive is a romset (many chip ROMs, one game), never split or unpacked.
    romsets: bool = False
    # Where a game's readable title is: its DAT name (No-Intro, Redump) or its description
    # (arcade DATs name games by short set names such as "mslug").
    names_from: Literal["name", "description"] = "name"
    # The DAT's file name at a source whose URL takes {dat_file} (FBNeo).
    dat_file: str | None = None
    # igir --merge-roms modes to identify with, each in its own run; a file is identified by
    # any of them (arcade sets are split or non-merged, and igir must be told which).
    igir_merge_modes: list[str] = Field(default_factory=list)
    # False: no source publishes this platform's DAT (Switch); only an upload can add one.
    dat_download: bool = True
    # Identified by title ID (Switch, `title_ids`), with or without a DAT: a base game, its
    # update and its DLC are one game; the base is ranked, DLC kept, updates proposed.
    title_ids: bool = False
    # TOSEC: the pack's DATs merged into this platform's DAT, by the start of their names
    # (the TOSEC download is offered when set).
    tosec_prefixes: list[str] = Field(default_factory=list)
    # The pack folder those DATs are in (None: the TOSEC source's member_dir); disc systems
    # are under TOSEC-ISO/.
    tosec_dir: str | None = None
    # ROM formats kept as they are (also in rom_extensions): never converted, and never
    # discarded on a name match or for a version in another format (Dreamcast .cdi: a CD-R
    # image chdman cannot read, often a cut-down rip of a GD-ROM).
    # Archives may hold other files besides the game's ROMs (.url, .nfo, .txt): igir is run
    # with --allow-excess-sets, and an archive's identification stands only when every ROM
    # file in it is one of the game's (by CRC32), so a several-games archive is never one.
    excess_files: bool = False
    # The default ranking criteria for this platform's folders (None: the global default).
    ranking_criteria: list[str] | None = None


class PlatformsConfig(_Strict):
    enabled: list[str]
    archive_extensions: list[str]
    # Disc image formats that are a container of their own (a target can produce them).
    disc_formats: list[str]
    # Switch packages, each a container of its own (NSP is a target).
    package_formats: list[str] = Field(default_factory=list)
    # Images already stripped of data (scrubbed, trimmed): never converted further, only
    # flagged. Shell patterns on the file name, case-insensitive.
    lossy_patterns: list[str] = Field(default_factory=list)
    targets: dict[str, TargetConfig]
    profiles: dict[str, PlatformProfile]

    @model_validator(mode="after")
    def _consistent(self) -> "PlatformsConfig":
        missing = [p for p in self.enabled if p not in self.profiles]
        if missing:
            raise ValueError(f"platforms.enabled lists platforms without a profile: {missing}")
        containers = {*self.archive_extensions, *self.disc_formats, *self.package_formats, PLAIN}
        for target_id, target in self.targets.items():
            if target.produces not in containers:
                raise ValueError(f"target {target_id}: unknown container {target.produces}")
        for platform_id, profile in self.profiles.items():
            unknown = [t for t in profile.targets if t not in self.targets]
            if unknown:
                raise ValueError(f"platform {platform_id}: unknown targets {unknown}")
            if profile.default_target not in profile.targets:
                raise ValueError(f"platform {platform_id}: default_target not in its targets")
            unknown_criteria = set(profile.ranking_criteria or []) - set(RANKING_CRITERIA)
            if unknown_criteria:
                raise ValueError(
                    f"platform {platform_id}: unknown ranking criteria {sorted(unknown_criteria)}"
                )
            if profile.dat_family not in DAT_FAMILIES:
                raise ValueError(
                    f"platform {platform_id}: dat_family must be one of {DAT_FAMILIES}"
                )
            if profile.kind not in PLATFORM_KINDS:
                raise ValueError(f"platform {platform_id}: kind must be one of {PLATFORM_KINDS}")
        return self

    def enabled_profiles(self) -> dict[str, PlatformProfile]:
        return {p: self.profiles[p] for p in self.enabled}


class DatSourceConfig(_Strict):
    label: str
    # The source's name where space is short (the Matching table's "Matched by").
    short_label: str
    identification_only: bool
    url_template: str | None = None
    website: str | None = None
    # The DAT families this source has (empty: every family).
    families: list[str] = Field(default_factory=list)
    # A pack found through a release index (TOSEC): the index page, the regex of release
    # page links on it, the regex of the pack link on a release page, the pack's DAT folder,
    # and where the downloaded pack is kept (relative to the data directory) for the next
    # platform.
    index_url: str | None = None
    release_pattern: str | None = None
    pack_pattern: str | None = None
    member_dir: str | None = None
    cache_dir: str | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)


class DatFamilyConfig(_Strict):
    label: str
    # The libretro-database directory with this family's DATs.
    libretro_dir: str
    # Retool's clone lists for it are named "<DAT name> <suffix>.json".
    clonelist_suffix: str


# The online lookups as entries of a platform's identification order.
LOOKUP_ENTRIES = ("hasheous",)


class DatsConfig(_Strict):
    directory: str
    families: dict[str, DatFamilyConfig]
    sources: dict[str, DatSourceConfig]
    # Suffixes a platform's DAT name may carry (format variants); any other names another set.
    variant_suffixes: list[str]
    download_timeout_seconds: float = Field(gt=0)
    max_upload_bytes: int = Field(gt=0)
    user_agent: str
    auto_activate_new: bool
    # Sources and online lookups, in the order they identify files by default.
    priority: list[str]

    @model_validator(mode="after")
    def _known_sources(self) -> "DatsConfig":
        required = {"libretro", "nointro", "upload"}
        if not required <= set(self.sources):
            raise ValueError(f"dats.sources must define {sorted(required)}")
        known = set(self.sources) | set(LOOKUP_ENTRIES)
        if set(self.priority) != known or len(self.priority) != len(known):
            raise ValueError(f"dats.priority must list each of {sorted(known)} once")
        if not self.sources["libretro"].url_template:
            raise ValueError("dats.sources.libretro.url_template is required")
        return self


class TitleDbConfig(_Strict):
    label: str
    short_label: str
    website: str
    url_template: str
    languages_url: str
    versions_url: str
    versions_file: str
    contents_url: str
    contents_file: str
    optional_content_types: list[int]
    entry_prefix: str
    file_pattern: str
    featured: list[str]
    timeout_seconds: float = Field(gt=0)
    max_download_bytes: int = Field(gt=0)
    languages_ttl_seconds: float = Field(gt=0)
    name_replacements: dict[str, str]
    release_format: str
    release_display: str
    game_category: str
    demo_category: str
    version_format: str


class IgirConfig(_Strict):
    binary: str
    cache_dir: str
    work_dir: str
    timeout_seconds: float = Field(gt=0)
    min_bytes_per_second: float = Field(gt=0)
    max_timeout_seconds: float = Field(gt=0)
    default_reader_threads: int = Field(gt=0)
    default_pool_threads: int = Field(gt=0)
    max_threads: int = Field(gt=0)


HASHEOUS_NAME_FROM = ("rom", "game")
# "source": the source names games as the platform's DAT does (its system is the DAT's
# name), so its name is taken. "dat_name": its answer identifies a file only with a name one
# of the platform's DATs lists; any other name is a hint for the suggestions.
HASHEOUS_TRUST = ("source", "dat_name")


class HasheousSource(_Strict):
    label: str
    name_from: str
    trust: str = "source"

    @model_validator(mode="after")
    def _known(self) -> "HasheousSource":
        if self.name_from not in HASHEOUS_NAME_FROM:
            raise ValueError(f"name_from must be one of {HASHEOUS_NAME_FROM}")
        if self.trust not in HASHEOUS_TRUST:
            raise ValueError(f"trust must be one of {HASHEOUS_TRUST}")
        return self


class HasheousConfig(_Strict):
    url: str
    site: str
    timeout_seconds: float = Field(gt=0)
    user_agent: str
    sources: dict[str, HasheousSource]
    not_found_ttl_days: float = Field(ge=0)


class ChdLookupConfig(_Strict):
    node: str
    script: str
    chdman_module: str
    chunk_bytes: int = Field(gt=0)
    timeout_seconds: float = Field(gt=0)
    min_bytes_per_second: float = Field(gt=0)
    audio_track_types: list[str]


class HashingConfig(_Strict):
    chunk_bytes: int = Field(gt=0)
    probe_bytes: int = Field(gt=0)
    workers: int = Field(gt=0)


class LookupsConfig(_Strict):
    chd: ChdLookupConfig
    hasheous: HasheousConfig


class FuzzyConfig(_Strict):
    min_score: float = Field(ge=0, le=1)
    max_suggestions: int = Field(ge=0)
    auto_match_threshold: float | None = Field(default=None, ge=0, le=1)


class ArchivesConfig(_Strict):
    seven_zip_binary: str
    list_timeout_seconds: float = Field(gt=0)


class JobsConfig(_Strict):
    scan_workers: int = Field(gt=0)
    max_scan_workers: int = Field(gt=0)
    conversion_runs: int = Field(gt=0)
    other_runs: int = Field(gt=0)
    conversion_workers: int = Field(gt=0)
    max_conversion_workers: int = Field(gt=0)

    @model_validator(mode="after")
    def _default_within_max(self):
        if self.scan_workers > self.max_scan_workers:
            raise ValueError("jobs.scan_workers is above jobs.max_scan_workers")
        if self.conversion_workers > self.max_conversion_workers:
            raise ValueError("jobs.conversion_workers is above jobs.max_conversion_workers")
        return self

    progress_interval_seconds: float = Field(ge=0)


class ChdmanConfig(_Strict):
    binary: str
    timeout_seconds: float = Field(gt=0)
    # Extra options for createcd/createdvd (codecs, hunk size, processors); empty: chdman's.
    create_args: list[str] = Field(default_factory=list)


class DolphinConfig(_Strict):
    binary: str
    # Dolphin's user folder for its temporary files, relative to the data directory.
    user_dir: str
    timeout_seconds: float = Field(gt=0)
    # Options for `dolphin-tool convert` (format, block size, codec, level).
    convert_args: list[str]


class ApplyConfig(_Strict):
    copy_chunk_bytes: int = Field(gt=0)
    temp_suffix: str = Field(min_length=1)
    # Wrapping a ROM in a zip: deflate at this level (zlib checks the range).
    zip_compress_level: int = Field(ge=0)
    # Extracting one member from a 7z archive must finish within this many seconds.
    extract_timeout_seconds: int = Field(gt=0)
    extract_min_bytes_per_second: float = Field(gt=0)
    # A disc conversion unpacks and checks its tracks in a directory with this suffix beside
    # the output; one left behind by a restart is removed at start-up.
    work_suffix: str = Field(min_length=1)
    # A tool running for a conversion that is being stopped is killed within this many seconds.
    stop_poll_seconds: float = Field(gt=0)


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


class SwappedOrder(_Strict):
    label: str
    magic_hex: str
    word_bytes: int = Field(gt=1)

    @model_validator(mode="after")
    def _hex(self) -> "SwappedOrder":
        bytes.fromhex(self.magic_hex)
        return self


class ByteOrderConfig(_Strict):
    magic_offset: int = Field(ge=0)
    native_magic_hex: str
    native_extension: str
    swapped: list[SwappedOrder] = Field(min_length=1)

    @model_validator(mode="after")
    def _same_length(self) -> "ByteOrderConfig":
        native = bytes.fromhex(self.native_magic_hex)
        if any(len(bytes.fromhex(s.magic_hex)) != len(native) for s in self.swapped):
            raise ValueError("every byte order's magic must be as long as the native one")
        return self


class NcchProofConfig(_Strict):
    """Where an NCCH partition keeps the SHA-256s that prove its decrypted data (defaults.yaml
    explains each field)."""

    hash_bytes: int = Field(gt=0)
    ncch_header_bytes: int = Field(gt=0)
    exheader_hash_offset: int = Field(ge=0)
    exheader_size_offset: int = Field(ge=0)
    exheader_hashed_bytes: int = Field(gt=0)
    logo_hash_offset: int = Field(ge=0)
    logo_region_offset: int = Field(ge=0)
    exefs_region_offset: int = Field(ge=0)
    exefs_hash_region_offset: int = Field(ge=0)
    exefs_hash_offset: int = Field(ge=0)
    romfs_region_offset: int = Field(ge=0)
    romfs_hash_region_offset: int = Field(ge=0)
    romfs_hash_offset: int = Field(ge=0)
    exefs_header_bytes: int = Field(gt=0)
    exefs_files: int = Field(gt=0)
    exefs_entry_bytes: int = Field(gt=0)
    exefs_name_bytes: int = Field(gt=0)
    ivfc_magic: str
    ivfc_header_bytes: int = Field(gt=0)
    ivfc_master_size_offset: int = Field(ge=0)
    ivfc_levels_offset: int = Field(ge=0)
    ivfc_levels: int = Field(gt=0)
    ivfc_level_bytes: int = Field(gt=0)
    ivfc_level_size_offset: int = Field(ge=0)
    ivfc_level_block_offset: int = Field(ge=0)
    read_chunk_bytes: int = Field(gt=0)
    report_unit: str
    report_unit_bytes: int = Field(gt=0)


class NcsdConfig(_Strict):
    magic: str
    magic_offset: int = Field(ge=0)
    image_size_offset: int = Field(ge=0)
    partition_table_offset: int = Field(ge=0)
    flags_offset: int = Field(ge=0)
    media_unit_flag: int = Field(ge=0)
    media_unit_bytes: int = Field(gt=0)
    ncch_magic: str
    ncch_magic_offset: int = Field(ge=0)
    ncch_flags_offset: int = Field(ge=0)
    crypto_flag: int = Field(ge=0)
    no_crypto_mask: int = Field(gt=0)
    # The NCCH's product code ("CTR-P-AWAE"), NUL-padded, readable without keys.
    product_code_offset: int = Field(ge=0)
    product_code_bytes: int = Field(gt=0)
    partition_count: int = Field(gt=0)
    partition_entry_bytes: int = Field(gt=0)
    # A title encrypted with a seed: its seed is found in seeddb by program ID.
    seed_mask: int = Field(gt=0)
    program_id_offset: int = Field(ge=0)
    program_id_bytes: int = Field(gt=0)
    proof: NcchProofConfig


class DecryptionConfig(_Strict):
    # Where the keys uploaded in the web UI are kept, relative to the data directory.
    keys_dir: str
    # The ARM9 BootROM: a full dump or its protected half is accepted (the protected half
    # is the last protected_bytes of a full one) and the protected half is stored as boot9_file.
    boot9_file: str
    boot9_sizes: list[int] = Field(min_length=1)
    protected_bytes: int = Field(gt=0)
    # Seeds for titles encrypted with one (digital releases): a header holding the entry
    # count (little-endian u32), then one entry per seed.
    seeddb_file: str
    seeddb_header_bytes: int = Field(gt=0)
    seeddb_count_bytes: int = Field(gt=0)
    seeddb_entry_bytes: int = Field(gt=0)
    seeddb_title_id_bytes: int = Field(gt=0)
    max_upload_bytes: int = Field(gt=0)
    # The stored keys' permission bits (only the app's user may read them).
    file_mode: int = Field(gt=0)
    # Added to the image's name for the decrypted output ("Game (Decrypted).3ds"), so it
    # never takes the encrypted original's name, which a restore needs back.
    output_suffix: str


class CsoConfig(_Strict):
    magic: str
    # struct formats: the header (magic, header size, image size, block size, version,
    # index shift) and one index entry.
    header: str
    index_entry: str
    versions: list[int]
    # The index entry bit that marks a block stored as it is (not deflated).
    plain_bit: int = Field(ge=0)
    # zlib window bits for the blocks' raw deflate streams (negative: no zlib header).
    window_bits: int


class TitleIdConfig(_Strict):
    digits: int = Field(gt=0)
    # Title IDs are hexadecimal; a ticket's rights ID has rights_id_digits.
    radix: int = Field(gt=1)
    rights_id_digits: int = Field(gt=0)
    low_hex: str
    update_low_hex: str
    dlc_step_hex: str
    name_pattern: str
    version_pattern: str
    display_prefix: str
    display_pattern: str
    name_end_pattern: str
    pfs0_magic: str
    pfs0_header: str
    pfs0_entry: str
    max_entries: int = Field(gt=0)
    ticket_suffix: str
    cnmt_xml_suffix: str
    nca_suffixes: list[str]
    cnmt_nca_suffix: str
    version_step: int = Field(gt=0)
    max_cnmt_xml_bytes: int = Field(gt=0)
    pfs0_extensions: list[str]


class NcaConfig(_Strict):
    keys_file: str
    header_key: str
    key_area_key_prefix: str
    titlekek_prefix: str
    generation_radix: int = Field(gt=1)
    header_key_bytes: int = Field(gt=0)
    key_bytes: int = Field(gt=0)
    header_bytes: int = Field(gt=0)
    sector_bytes: int = Field(gt=0)
    xts_reduction: int = Field(gt=0)
    xts_tweak_bits: int = Field(gt=0)
    magic_offset: int = Field(ge=0)
    magic: str
    content_type_offset: int = Field(ge=0)
    meta_type: int
    control_type: int
    key_generation_offset: int = Field(ge=0)
    key_area_index_offset: int = Field(ge=0)
    key_generation2_offset: int = Field(ge=0)
    rights_id_offset: int = Field(ge=0)
    sections: int = Field(gt=0)
    section_table_offset: int = Field(ge=0)
    section_entry: str
    key_area_offset: int = Field(ge=0)
    ctr_key_index: int = Field(ge=0)
    fs_header_offset: int = Field(ge=0)
    fs_header_bytes: int = Field(gt=0)
    fs_kinds: str
    crypt_ctr: int
    pfs0_range_offset: int = Field(ge=0)
    romfs_range_offset: int = Field(ge=0)
    range: str
    section_ctr_offset: int = Field(ge=0)
    section_ctr_bytes: int = Field(gt=0)
    ctr_shift: int = Field(ge=0)
    aes_block_bytes: int = Field(gt=0)
    romfs_header: str
    romfs_file: str
    romfs_name_align: int = Field(gt=0)
    nacp_name: str
    display_version_offset: int = Field(ge=0)
    display_version_bytes: int = Field(gt=0)
    cnmt_suffix: str
    nca_suffix: str
    cnmt_header: str
    ticket_titlekey_offset: int = Field(ge=0)
    ticket_type_offset: int = Field(ge=0)
    ticket_common: int
    max_read_bytes: int = Field(gt=0)


class SwitchPackageConfig(_Strict):
    ncz_header_bytes: int = Field(gt=0)
    section_magic: str
    block_magic: str
    count: str
    section: str
    block_header: str
    block_size: str
    ctr_crypto_types: list[int]
    counter_prefix_bytes: int = Field(gt=0)
    ncz_suffix: str
    nca_suffix: str
    cnmt_suffix: str
    xci_magic_offset: int = Field(ge=0)
    xci_magic: str
    xci_hfs0: str
    xci_hfs0_offset: int = Field(ge=0)
    hfs0_magic: str
    hfs0_header: str
    hfs0_entry: str
    secure_partition: str
    max_entries: int = Field(gt=0)
    pfs0_align: int = Field(gt=0)
    content_id_digits: int = Field(gt=0)
    chunk_bytes: int = Field(gt=0)


class TosecConfig(_Strict):
    # Country codes -> the region names ranking uses.
    countries: dict[str, str]
    # Development status tags that mark a pre-release.
    prerelease: list[str]
    # Tags that never keep games apart (video standard, copyright status).
    neutral: list[str]
    # Dump flag code -> rank (lower is better); a name with no flag ranks clean_rank.
    dump_flag_rank: dict[str, int]
    clean_rank: int


class NamesConfig(_Strict):
    regions: list[str]
    prerelease_tags: list[str]
    rerelease_tags: list[str]
    neutral_tags: list[str]
    tosec: TosecConfig


class StatisticsConfig(_Strict):
    categories: list[str]
    excluded_tags: list[str]
    tosec_excluded_flags: list[str]
    tosec_year_pattern: str
    note_labels: dict[str, str] = Field(default_factory=dict)


class GroupingConfig(_Strict):
    infer_from_dat_names: bool
    retool_clonelists_dir: Path


RANKING_CRITERIA = (
    "prerelease",
    "region",
    "language",
    "revision",
    "original",
    "parent",
    "dump",
)


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
    titledb: TitleDbConfig
    igir: IgirConfig
    archives: ArchivesConfig
    chdman: ChdmanConfig
    dolphin: DolphinConfig
    hashing: HashingConfig
    lookups: LookupsConfig
    fuzzy: FuzzyConfig
    jobs: JobsConfig
    apply: ApplyConfig
    headers: dict[str, list[HeaderRule]]
    byte_orders: dict[str, ByteOrderConfig] = Field(default_factory=dict)
    card_images: dict[str, NcsdConfig] = Field(default_factory=dict)
    cso: CsoConfig | None = None
    decryption: DecryptionConfig
    title_ids: TitleIdConfig | None = None
    nca: NcaConfig
    switch_package: SwitchPackageConfig
    names: NamesConfig
    statistics: StatisticsConfig
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


def load_settings(
    environ: dict[str, str] | None = None, overrides: dict[str, Any] | None = None
) -> Settings:
    """The defaults, with the data directory from the environment. `overrides` (deep-merged)
    is for tests only: nothing a user does reaches it."""
    environ = os.environ if environ is None else environ
    raw = deep_merge(load_defaults(), overrides or {})
    if DATA_DIR_ENV in environ:
        raw = deep_merge(raw, {"paths": {"data_dir": environ[DATA_DIR_ENV]}})
    try:
        return Settings.model_validate(raw)
    except ValueError as exc:
        raise ConfigError(f"invalid configuration: {exc}") from exc
