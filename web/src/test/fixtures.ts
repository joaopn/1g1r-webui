import type { Game, Meta } from "@/lib/types";

const size = (rem: number) => ({ rem, min: rem / 2, max: rem * 3 });

export const META: Meta = {
  app: { name: "1g1r-webui", source_url: "" },
  ui: {
    page_size: 50,
    poll_interval_ms: 1000,
    hash_display_length: 12,
    byte_unit_base: 1024,
    byte_units: ["B", "KiB", "MiB"],
    sidebar: { width_rem: 15, min_rem: 11, max_rem: 30 },
    platform_icon_width_rem: 3.25,
    resize_step_rem: 0.25,
    resize_shift_multiplier: 4,
    rem_fallback_px: 16,
    game_columns: Object.fromEntries(
      [
        "keep",
        "game",
        "status",
        "versions",
        "source",
        "file",
        "dat_name",
        "region",
        "languages",
        "revision",
        "flags",
        "size",
        "match",
        "proposed",
      ].map((id) => [id, size(8)]),
    ),
    game_columns_default: ["keep", "game", "status", "file", "region", "size", "match", "proposed"],
  },
  platforms: {
    nes: {
      name: "Nintendo Entertainment System",
      short: "NES",
      kind: "console",
      nointro_dat: "Nintendo - NES",
      rom_extensions: ["nes"],
      targets: ["zip", "plain"],
      default_target: "zip",
    },
    gb: {
      name: "Game Boy",
      short: "GB",
      kind: "handheld",
      nointro_dat: "Nintendo - Game Boy",
      rom_extensions: ["gb"],
      targets: ["zip", "plain"],
      default_target: "zip",
    },
  },
  targets: {
    zip: { label: "Zip (TorrentZip)", description: "" },
    plain: { label: "Unpacked", description: "" },
  },
  dat_sources: { libretro: { label: "libretro-database mirror", identification_only: true } },
  ranking: {
    criteria: ["prerelease", "region", "language", "revision", "original"],
    labels: {
      prerelease: "full release over pre-release",
      region: "region priority",
      language: "language priority",
      revision: "newest revision",
      original: "original over re-release",
    },
    default: {
      criteria: ["prerelease", "region"],
      regions: ["World", "USA"],
      languages: ["En"],
      multi_region: "best",
    },
  },
  label_pattern: "^[a-z0-9][a-z0-9._-]*$",
  discarded_root: "/roms/discarded",
};

const version = (
  rel: string,
  regions: string[],
  extra: Partial<Game["versions"][number]> = {},
) => ({
  rel_path: rel,
  game_name: rel.replace(/\.zip$/, ""),
  method: "dat-checksum",
  probability: 1,
  regions,
  languages: [],
  revision: null,
  prerelease: false,
  rerelease: false,
  tags: [],
  size: 2048,
  keep: false,
  operation: null,
  ...extra,
});

export const GAMES: Game[] = [
  {
    key: "name:Contra",
    name: "Contra",
    source: "dat-name",
    status: "decided",
    reason: "region priority",
    kept: "Contra (USA).zip",
    candidates: ["Contra (USA).zip"],
    versions: [
      version("Contra (Japan).zip", ["Japan"], {
        operation: "/roms/discarded/nes/1g1r/Contra (Japan).zip",
      }),
      version("Contra (USA).zip", ["USA"], { keep: true }),
    ],
  },
  {
    key: "name:Gradius",
    name: "Gradius",
    source: "dat-name",
    status: "undecided",
    reason: "enabled criteria do not separate these versions",
    kept: null,
    candidates: ["Gradius (USA).zip", "Gradius (USA) (Rev 1).zip"],
    versions: [
      version("Gradius (USA).zip", ["USA"]),
      version("Gradius (USA) (Rev 1).zip", ["USA"], { revision: "Rev 1" }),
    ],
  },
  {
    key: "game:Arkanoid (Japan)",
    name: "Arkanoid",
    source: "single",
    status: "single",
    reason: "only version",
    kept: "Arkanoid (Japan).zip",
    candidates: ["Arkanoid (Japan).zip"],
    versions: [version("Arkanoid (Japan).zip", ["Japan"], { keep: true })],
  },
];
