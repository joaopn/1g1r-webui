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
/** Stored console keys: boot9 and seeddb (3DS), and prod.keys (Switch: the key generations
 * it holds). */
export type KeyStatus = { boot9: boolean; seeddb: number | null; prod_keys: number | null };

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
    ignored_columns: Record<string, ColumnSize>;
    ignored_columns_default: string[];
    updates_columns: Record<string, ColumnSize>;
    updates_columns_default: string[];
    rename_columns: Record<string, ColumnSize>;
    rename_columns_default: string[];
    statistics_columns: Record<string, ColumnSize>;
    statistics_columns_default: string[];
    statistics_source_rem: number;
    statistics_source_gap_rem: number;
    missing_columns: Record<string, ColumnSize>;
    missing_columns_default: string[];
    percent_digits: number;
    notifications: { limit: number; idle_poll_ms: number };
  };
  platforms: Record<string, Platform>;
  archive_extensions: string[];
  targets: Record<string, Target>;
  dat_sources: Record<
    string,
    {
      label: string;
      short_label: string;
      identification_only: boolean;
      website?: string;
      /** It holds platforms' side sets (Non-Redump, PSN): its buttons say its short name. */
      side?: boolean;
    }
  >;
  /** Switch names from titledb: each region file ("US.en") is an order entry
   * "<entry_prefix><file>"; `featured` files get a button of their own. */
  titledb: {
    label: string;
    short_label: string;
    website: string;
    entry_prefix: string;
    featured: string[];
  };
  ranking: { criteria: string[]; labels: Record<string, string>; default: Ranking };
  label_pattern: string;
  discarded_root: string;
  /** The naming templates of the Rename tab, by id (`keep` renames nothing). */
  rename_templates: Record<string, RenameTemplate>;
};

export type RenameTemplate = { label: string; description: string; example: string };

/** A scan or run in the notifications panel (`GET /api/notifications`). */
export type Notification = {
  /** "scan-<id>" or "run-<id>". */
  id: string;
  kind:
    | "scan"
    | "check"
    | "conversion"
    | "1g1r"
    | "unmatched"
    | "set-aside"
    | "updates"
    | "empty"
    | "restore"
    | "rename"
    | "rename-back";
  title: string;
  folder_label: string;
  status: "running" | "done" | "failed";
  started_at: string;
  finished_at: string | null;
  message: string;
  /** A running scan's step. */
  stage: string | null;
  done: number | null;
  total: number | null;
  failed: number;
};

export type Scan = {
  id: number;
  /** "check": Check files (what conversion needs, nothing hashed); "identify": a Scan. */
  kind: "check" | "identify";
  status: "running" | "done" | "failed";
  started_at: string;
  finished_at: string | null;
  message: string | null;
  /** While running: the step it is on (null until it starts) and that step's file count. */
  stage: string | null;
  files_done: number | null;
  files_total: number | null;
  /** While a step waits on igir: its command line, as a shell would show it. */
  command: string | null;
  /** Every igir command the scan ran, in order; kept after it ends. */
  commands: string[];
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

/** One step of a platform's identification order: a source's active DAT, or a lookup. */
export type DatOrderEntry = {
  id: string;
  label: string;
  /** Identifies files: not switched off here nor on every platform. */
  on: boolean;
  /** Switched off on this platform. */
  own_off: boolean;
  /** Switched off on every platform (Which DATs to use?). */
  global_off: boolean;
  lookup: boolean;
  dat: DatVersion | null;
  pinned: boolean;
};

/** A DAT source or online lookup, on or off for every platform, and the platforms it serves. */
export type DatSource = {
  id: string;
  label: string;
  short_label: string;
  lookup: boolean;
  /** A platform's own extra DAT (Non-Redump, PSN, titledb). */
  side: boolean;
  on: boolean;
  /** Any platform (uploads, online lookups). */
  every: boolean;
  /** The enabled platforms it has a DAT for, with that DAT's name where the platform names one. */
  platforms: { platform: string; dat_name: string | null }[];
};

export type Summary = {
  counts: Record<string, number>;
  roms: number;
  /** Every file in the folder, as last scanned. */
  bytes: number;
  identified: number;
  unmatched: number;
  /** Files a conversion is proposed for (cue sheets and tracks included): identified once
   * converted, neither versions nor unmatched until then. */
  waiting?: number;
  /** Listed (by Check files, or new since the last scan) but not looked at by a Scan yet. */
  unscanned?: number;
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
  /** Hidden from the sidebar and Home; still a set (Settings → Folders). */
  hidden: boolean;
  /** Filename patterns the set ignores, whether they are the configured default, and files
   * ignored by their path in the set. */
  ignored_patterns: string[];
  ignored_patterns_default: boolean;
  ignored_files: string[];
  /** Identified by title ID (Switch): the set has an Updates tab. */
  title_ids: boolean;
  /** The Rename tab's naming template, and those the platform offers. */
  rename_template: string;
  rename_templates: string[];
};

export type FolderCard = FolderInfo & {
  /** The latest run of either kind, and the latest Scan. */
  scan: Scan | null;
  last_scan: Scan | null;
  dat: DatVersion | null;
  summary: Summary;
  /** Without an active DAT: where the platform's DAT downloads from by default. */
  dat_download: { source: string; label: string } | null;
  /** No active DAT, and the platform needs one to identify anything. */
  needs_dat: boolean;
  /** Which run is due ("Needs scanning"): Check files before any run, else a Scan when
   * never scanned, after a failed one, a DAT change or a conversion; null when none is. */
  needs: "check" | "identify" | null;
  needs_scan: boolean;
  counts: Record<string, number>;
  reclaim_bytes: number;
  conversion: ConversionCounts;
  /** ROM files with nothing left to do, and the rest. */
  progress: { processed: number; to_process: number; to_match: number; to_convert: number };
  /** Title-ID sets: their updates, the older ones proposed for discarded/, and those whose
   * version could not be read; null for other sets. */
  updates: UpdateCounts | null;
  /** The Rename tab: the set's template and how many files it proposes to rename. */
  rename: RenameCounts & { template: string };
  discarded: { files: number; bytes: number };
  /** The conversion running in the folder: files finished of the planned total, files failed,
   * and whether a stop was asked for. */
  converting: {
    done: number;
    total: number;
    failed: number;
    stopping: boolean;
    /** Not begun: the folder whose conversion it waits for ("" when about to begin). */
    waiting_for: string | null;
  } | null;
  /** An apply or a restore (conversions included) runs in the folder. */
  running: boolean;
  warnings: FolderWarning[];
};

/** "info" is a hint shown small, with a link to where it is acted on. */
export type FolderWarning = {
  level: "warn" | "bad" | "info";
  text: string;
  link?: { to: string; text: string } | null;
};

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

/** A file the set does not process; `ignored_by` says which entry of the ignore list leaves it
 * out ("file", a pattern, "hidden" for a dot file), null when none does now. */
export type OtherFile = FileRow & { ignored_by: string | null };

/** A file left alone because it is not in a format the platform supports. */
export type UnsupportedFile = { rel_path: string; size: number; reason: string };

export type FolderDetail = FolderInfo & {
  dat_order: DatOrderEntry[];
  dat_order_own: boolean;
  scan: Scan | null;
  last_scan: Scan | null;
  dat: DatVersion | null;
  summary: Summary;
  unmatched: FileRow[];
  /** ROM files a conversion is proposed for: identified once converted. */
  convert_first: FileRow[];
  others: OtherFile[];
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
  /** The DAT that identified it (null: an online lookup or a title ID). */
  dat: {
    source: string;
    /** Short, for the table: "No-Intro", "libretro". */
    label: string;
    source_label: string;
    version: string | null;
    header_name: string;
  } | null;
  probability: number;
  regions: string[];
  languages: string[];
  /** From titledb (title-ID platforms), when a titledb file lists the title. */
  publisher: string | null;
  release: string | null;
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
  | "applied"
  /** A file nothing identified, shown as a row of its own (never from the API's games). */
  | "unmatched"
  /** A file waiting for its conversion, shown as a row of its own: identified once converted. */
  | "convert first";

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
  /** What to type to confirm, when not the folder label (every set at once). */
  confirm?: string;
  /** Sets left alone (their folder cannot be found), every set at once only. */
  skipped?: { label: string; reason: string }[];
};

export type Run = {
  id: number;
  folder_label: string;
  kind: "apply" | "restore";
  scope: string;
  status: "running" | "done" | "failed";
  total: number;
  done: number;
  /** A stop was asked for (conversions only); a stopped run's message starts "stopped:". */
  stopping: boolean;
  message: string;
  started_at: string;
  finished_at: string | null;
  /** Steps that failed; `action` "convert" is a file a conversion could not convert. */
  failed: { rel_path: string; error: string; action: string }[];
  /** Steps done with a warning (a disc track padded to a whole sector). */
  warnings: { rel_path: string; warning: string }[];
  /** A conversion not begun yet: the folder whose conversion it waits for ("" when about to
   * begin); null otherwise. */
  waiting_for: string | null;
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
  /** Title-ID games: the updates and DLC of the game, listed on the Updates & DLC tab. */
  extras?: { updates: number; dlc: number };
};

export type DatRow = {
  platform: string;
  /** The first DAT of the order. */
  active: DatVersion | null;
  order: DatOrderEntry[];
  /** The platform has its own order (else it follows the default one). */
  own_order: boolean;
  versions: DatVersion[];
  folders: string[];
  /** Where this platform's DAT can be downloaded from, one button each. */
  downloads: { source: string; label: string; identification_only: boolean }[];
  /** Pages its DAT is downloaded from by hand (DAT-o-MATIC), then uploaded. */
  pages: { source: string; label: string; url: string }[];
  /** Its games have title IDs (Switch): titledb region files name them. */
  titledb: boolean;
};

/** Renaming for every set: off, or each platform's recommended template. */
export type RenameMode = "disabled" | "recommended";

export type SettingsData = {
  targets: Record<string, string>;
  /** `custom`: some set picked a template of its own. */
  rename: { mode: RenameMode; custom: boolean };
  lookups: { hasheous: boolean };
  hasheous: {
    site: string;
    url: string;
    /** Named like the platform's DAT: their names are taken. */
    sources: string[];
    /** Named their own way: identify only with a name one of the platform's DATs lists. */
    other_sources: string[];
    not_found_ttl_days: number;
  };
  fuzzy: { min_score: number; max_suggestions: number; auto_match_threshold: number | null };
  /** How many folder scans run at a time: the value in use, the default and the most. */
  parallel_scans: { value: number; default: number; max: number };
  /** How many files one conversion run converts at a time. */
  parallel_conversions: { value: number; default: number; max: number };
  /** Rows per page of every table. */
  page_size: { value: number; default: number; max: number };
  /** Threads per igir run; null: igir's own (its default readers and pool). */
  igir_threads: {
    value: number | null;
    default_readers: number;
    default_pool: number;
    max: number;
  };
  effective_yaml: string;
  library_file: string;
};

export type Browse = {
  mount: string;
  path: string;
  location: string;
  children: string[];
  suggested_label: string;
};

/** One subfolder offered by "Automatch folders". */
export type SetCandidate = {
  name: string;
  path: string;
  /** The platform its name matches exactly, or null. */
  platform: string | null;
  note: string;
  label: string;
  /** Why it cannot be a set (already one, or overlapping one), or null. */
  problem: string | null;
  items: number | null;
};

export type SetCandidates = { mount: string; path: string; location: string; rows: SetCandidate[] };

export type Target = { label: string; description: string; produces: string };

export type ConversionStatus =
  | "wrap"
  | "unwrap"
  | "repack"
  | "make chd"
  | "make rvz"
  | "byteswap"
  | "decrypt"
  | "make nsp"
  | "flagged"
  | "part"
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

export type Conversion = {
  counts: ConversionCounts;
  rows: ConversionRow[];
  /** Flagged, or failed in the last conversion: moved to discarded/ in one go. */
  cannot_convert: string[];
};

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
  suggestions: { game_name: string; score: number }[];
};

/** GET /statistics: how much of each local DAT every folder covers (games only). */
export type Coverage = { covered: number; total: number; dat: DatVersion };

export type StatisticsFolder = {
  label: string;
  platform: string;
  platform_short: string;
  roms: number;
  identified: number;
  /** The folder's files as last scanned, and what is in its discarded/ folder (both live). */
  bytes: number;
  discarded_bytes: number;
  /** By DAT source; a source the folder's platform has no DAT of is absent. */
  coverage: Record<string, Coverage>;
  /** When the figures were computed (they are kept until Refresh). */
  computed_at: string;
  /** The folder's files, identities or DATs changed since. */
  stale: boolean;
};

export type DatInfo = {
  id: string;
  label: string;
  dats: number;
  identification_only: boolean;
  checksums: string[];
  categories: string[];
  parent_clone: boolean;
  bios: boolean;
  serials: boolean;
  years: boolean;
  publishers: boolean;
  /** titledb: games are title IDs, found by the ID read inside a file. */
  title_ids?: boolean;
};

export type Statistics = {
  sources: { id: string; label: string; short_label: string }[];
  folders: StatisticsFolder[];
  dat_info: DatInfo[];
  rules: {
    categories: string[];
    excluded_tags: string[];
    tosec_excluded_flags: string[];
    tosec_year_pattern: string;
  };
};

export type MissingGame = {
  key: string;
  name: string;
  versions: number;
  years: string | null;
  publishers: string | null;
  regions: string | null;
  languages: string | null;
  serials: string | null;
  /** Obs: the versions' other name tags ("Unlicensed", "Virtual Console"). */
  notes: string | null;
  /** A note is a spelled-out one (Unlicensed): sorting by Obs keeps these together. */
  marked: boolean;
  entries: string[];
};

export type Missing = { dat: DatVersion; covered: number; total: number; rows: MissingGame[] };

/** `unreadable`: updates without a readable version (prod.keys read it); `dlc`: DLC listed. */
export type UpdateCounts = {
  total: number;
  proposed: number;
  unknown: number;
  unreadable: number;
  dlc: number;
};

/** One update of a title-ID game (the Updates tab). */
export type UpdateRow = {
  group_key: string;
  game: string;
  rel_path: string;
  title_id: string;
  /** From the file's content metadata; null when it could not be read. */
  version: number | null;
  /** Which update it is: 1 for the first. */
  release: number | null;
  /** The version shown to players ("1.0.2"), read with prod.keys. */
  display_version: string | null;
  size: number | null;
  status: "newest" | "older" | "kept" | "version unknown" | "left alone" | "discarded" | "dlc";
  role: "update" | "dlc";
  /** What the file says of itself (its content archives against titledb's list). */
  notes: string[];
  reason: string;
  /** Where the proposed move takes it; null when it stays. */
  operation: string | null;
  /** The move that took it to discarded/ (restore). */
  discarded: number | null;
  /** The newest update titledb knows for the game: version, which update, release date. */
  latest_version: number | null;
  latest_release: number | null;
  latest_date: string | null;
  /** The game's newest update here, and titledb knows a newer one. */
  newer: boolean;
};

/** A game of the set on the Updates & DLC tab (with or without updates or DLC): its newest
 * update's versions, whether titledb knows a newer one, and what its rows hold. */
export type UpdateGame = {
  group_key: string;
  game: string;
  display_version: string | null;
  version: number | null;
  /** Which update its newest one is (1 for the first). */
  release: number | null;
  newer: boolean;
  latest_release: number | null;
  latest_date: string | null;
  updates: number;
  dlc: number;
  to_discard: number;
  size: number;
  /** On titledb's newest update; null when that cannot be told (no titledb). */
  latest: boolean | null;
};

/** `newer`: games whose newest update here is older than one titledb knows. */
export type Updates = {
  updates: UpdateRow[];
  games: UpdateGame[];
  counts: UpdateCounts & { newer: number };
};

/** A ROM file of the Rename tab: the name its set's template proposes, or why none. */
export type RenameRow = {
  rel_path: string;
  size: number;
  /** The identified name the new one is built from (several joined), null if none. */
  game: string | null;
  method: string | null;
  status: "rename" | "named" | "skipped";
  new_path: string | null;
  reason: string;
  /** The file's path before its first rename, when the app renamed it. */
  original: string | null;
};

export type RenameCounts = {
  files: number;
  proposed: number;
  named: number;
  skipped: number;
  renamed: number;
};

export type Renames = {
  template: string;
  rows: RenameRow[];
  counts: RenameCounts;
};
