export type ColumnSize = { rem: number; min: number; max: number };

export type Platform = {
  name: string;
  short: string;
  kind: "console" | "handheld" | "arcade" | "computer";
  dat_name: string;
  rom_extensions: string[];
  targets: string[];
  default_target: string;
  /** Encrypted images can be decrypted with console keys the user adds (3DS). */
  decrypts: boolean;
};

/** Which console keys are stored (never the keys): boot9 there, and seeddb's seed count. */
export type KeyStatus = { boot9: boolean; seeddb: number | null };

export type Ranking = {
  criteria: string[];
  regions: string[];
  languages: string[];
  multi_region: "best" | "first";
};

export type Meta = {
  app: { name: string; source_url: string };
  ui: {
    page_size: number;
    dat_search_limit: number;
    poll_interval_ms: number;
    hash_display_length: number;
    byte_unit_base: number;
    byte_units: string[];
    sidebar: { width_rem: number; min_rem: number; max_rem: number };
    platform_icon_width_rem: number;
    resize_step_rem: number;
    resize_shift_multiplier: number;
    rem_fallback_px: number;
    game_columns: Record<string, ColumnSize>;
    game_columns_default: string[];
    conversion_columns: Record<string, ColumnSize>;
    conversion_columns_default: string[];
    discarded_columns: Record<string, ColumnSize>;
    discarded_columns_default: string[];
  };
  platforms: Record<string, Platform>;
  archive_extensions: string[];
  targets: Record<string, Target>;
  dat_sources: Record<string, { label: string; identification_only: boolean; website?: string }>;
  ranking: { criteria: string[]; labels: Record<string, string>; default: Ranking };
  label_pattern: string;
  discarded_root: string;
};

export type Scan = {
  id: number;
  status: "running" | "done" | "failed";
  started_at: string;
  finished_at: string | null;
  message: string | null;
};

export type DatVersion = {
  id: number;
  platform: string;
  source: string;
  header_name: string;
  version: string | null;
  sha1: string;
  game_count: number;
  has_parent_clone: number;
  matches_platform: number;
  added_at: string;
};

export type Summary = {
  counts: Record<string, number>;
  roms: number;
  identified: number;
  unmatched: number;
  /** Cue sheets and track files: versions once converted to one file. */
  waiting?: number;
  methods: Record<string, number>;
};

export type FolderInfo = {
  label: string;
  platform: string;
  mount: string;
  path: string;
  location: string | null;
  on_main_mount: boolean;
  target: string;
  discarded_to: string;
  delete_originals: boolean;
};

export type FolderCard = FolderInfo & {
  scan: Scan | null;
  dat: DatVersion | null;
  summary: Summary;
  counts: Record<string, number>;
  reclaim_bytes: number;
  conversion: ConversionCounts;
  discarded: { files: number; bytes: number };
  warnings: FolderWarning[];
};

export type FolderWarning = { level: "warn" | "bad"; text: string };

export type DiscardedFile = {
  rel_path: string;
  size: number;
  modified: string;
  restore_to: string | null;
  occupied: boolean;
  operation_id: number | null;
};

export type DiscardedReason = {
  id: string;
  label: string;
  description: string;
  known: boolean;
  bytes: number;
  files: DiscardedFile[];
};

export type Discarded = { root: string; files: number; bytes: number; reasons: DiscardedReason[] };

export type FileRow = { rel_path: string; size: number; kind: string };

/** A file left alone because it is not in a format the platform supports. */
export type UnsupportedFile = { rel_path: string; size: number; reason: string };

export type FolderDetail = FolderInfo & {
  scan: Scan | null;
  dat: DatVersion | null;
  summary: Summary;
  unmatched: FileRow[];
  others: FileRow[];
  unsupported: UnsupportedFile[];
  ranking: Ranking;
  ranking_is_default: boolean;
};

export type Version = {
  rel_path: string;
  game_name: string;
  /** The readable title: the DAT description for arcade sets, else the DAT name. */
  title: string;
  method: string;
  probability: number;
  regions: string[];
  languages: string[];
  revision: string | null;
  prerelease: boolean;
  rerelease: boolean;
  tags: string[];
  size: number | null;
  keep: boolean;
  operation: string | null;
  /** The apply operation that moved this version to discarded/, while it is there. */
  discarded: number | null;
  /** The other versions with byte-identical ROM data. */
  identical: string[];
  /** What the file's header says: "encrypted", "trimmed" (3DS card images). */
  notes: string[];
  /** Title-ID platforms (Switch): what the file is to its game. */
  role: "base" | "update" | "dlc" | null;
  /** Where the proposed move goes: 1g1r/, or duplicates/ for an identical copy. */
  discard_reason: "1g1r" | "duplicates" | "updates" | null;
};

export type GameStatus =
  | "single"
  | "decided"
  | "undecided"
  | "your pick"
  | "left alone"
  | "applied";

export type PlannedMove = {
  rel_path: string;
  group_key: string;
  action: "move" | "convert" | "delete" | "remove";
  source: string;
  destination: string | null;
  size: number;
};

export type ApplyPreview = {
  token: string;
  moves: PlannedMove[];
  bytes: number;
  problems: { rel_path: string; problem: string }[];
  busy: string | null;
};

export type PlannedConversion = {
  rel_path: string;
  output: string;
  size: number;
  /** Where the original goes; null when it is deleted. */
  original_to: string | null;
};

export type ConvertPreview = {
  token: string;
  conversions: PlannedConversion[];
  /** Originals the plan deletes: needs the typed folder label. */
  irreversible: number;
  bytes: number;
  problems: { rel_path: string; problem: string }[];
  busy: string | null;
};

export type GuardedPreview = {
  token: string;
  /** destination null: the file is deleted. */
  files: { rel_path: string; size: number; destination: string | null }[];
  irreversible: number;
  bytes: number;
  problems: { rel_path: string; problem: string }[];
  busy: string | null;
};

export type Run = {
  id: number;
  folder_label: string;
  kind: "apply" | "restore";
  scope: string;
  status: "running" | "done" | "failed";
  total: number;
  done: number;
  message: string;
  started_at: string;
  finished_at: string | null;
  failed: { rel_path: string; error: string }[];
};

export type Game = {
  key: string;
  name: string;
  source: string;
  status: GameStatus;
  reason: string;
  kept: string | null;
  candidates: string[];
  versions: Version[];
};

export type DatRow = {
  platform: string;
  active: DatVersion | null;
  pinned: boolean;
  versions: DatVersion[];
  folders: string[];
  /** Where this platform's DAT can be downloaded from, one button each. */
  downloads: { source: string; label: string; identification_only: boolean }[];
};

export type SettingsData = {
  targets: Record<string, string>;
  ignored_filenames: string[];
  lookups: { hasheous: boolean; screenscraper: boolean };
  hasheous: { site: string; url: string; sources: string[]; not_found_ttl_days: number };
  screenscraper: {
    site: string;
    url: string;
    /** Whether the credentials are set in the environment (never the values). */
    configured: boolean;
    environment: { devid: string; devpassword: string; user: string; password: string };
    min_interval_seconds: number;
    not_found_ttl_days: number;
    platforms: string[];
  };
  fuzzy: { min_score: number; max_suggestions: number; auto_match_threshold: number | null };
  effective_yaml: string;
  config_file: string;
  library_file: string;
};

export type Browse = {
  mount: string;
  path: string;
  location: string;
  children: string[];
  suggested_label: string;
};

export type Target = { label: string; description: string; produces: string; accepts: string[] };

export type ConversionStatus =
  | "wrap"
  | "unwrap"
  | "make chd"
  | "make rvz"
  | "byteswap"
  | "decrypt"
  | "flagged"
  | "part"
  | "accepted"
  | "done";

export type ArchiveMember = { name: string; size: number; crc32: string | null };

export type ConversionRow = {
  rel_path: string;
  size: number;
  container: string;
  members: ArchiveMember[];
  status: ConversionStatus;
  output: string | null;
  originals_to: string | null;
  reversible: boolean;
  verify: string | null;
  note: string;
  recipe: string | null;
  /** A cue sheet's track files, converted and moved with it. */
  parts: string[];
  disc_mode: string | null;
};

export type ConversionCounts = Record<ConversionStatus | "to_convert" | "all", number>;

export type Conversion = { counts: ConversionCounts; rows: ConversionRow[] };

export type LookupStatus =
  | "off"
  | "found"
  | "not found"
  | "other platform"
  | "not in the DAT"
  | "error"
  | "skipped";

export type UnmatchedFile = {
  rel_path: string;
  size: number;
  hash: { crc32: string; sha1: string } | null;
  hasheous: { status: LookupStatus; detail: string } | null;
  screenscraper: { status: LookupStatus; detail: string } | null;
  suggestions: { game_name: string; score: number }[];
};
