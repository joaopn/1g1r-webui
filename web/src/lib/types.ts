export type ColumnSize = { rem: number; min: number; max: number };

export type Platform = {
  name: string;
  short: string;
  kind: "console" | "handheld";
  nointro_dat: string;
  rom_extensions: string[];
  targets: string[];
  default_target: string;
};

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
  };
  platforms: Record<string, Platform>;
  targets: Record<string, { label: string; description: string }>;
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
};

export type FolderCard = FolderInfo & {
  scan: Scan | null;
  dat: DatVersion | null;
  summary: Summary;
  counts: Record<string, number>;
  reclaim_bytes: number;
};

export type FileRow = { rel_path: string; size: number; kind: string };

export type FolderDetail = FolderInfo & {
  scan: Scan | null;
  dat: DatVersion | null;
  summary: Summary;
  unmatched: FileRow[];
  others: FileRow[];
  ranking: Ranking;
  ranking_is_default: boolean;
};

export type Version = {
  rel_path: string;
  game_name: string;
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
};

export type GameStatus = "single" | "decided" | "undecided" | "your pick" | "left alone";

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
};

export type SettingsData = {
  targets: Record<string, string>;
  ignored_filenames: string[];
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
