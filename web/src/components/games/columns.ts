import { isNumberRecord, isStringArray, readJson, removeKey, writeJson } from "@/lib/storage";
import type { ColumnSize, Game, GameStatus, Version } from "@/lib/types";

/**
 * The Matching table's columns. Labels, sort keys and renderers live here; widths and the
 * default selection come from the server's config (`ui.game_columns*`), like every number.
 *
 * Group-level columns (Game, Status, Versions, Source) describe the game; the others
 * describe one version. On a game's own row, version columns show the kept version (or,
 * while undecided, nothing).
 */
export type ColumnId =
  | "keep"
  | "game"
  | "status"
  | "versions"
  | "source"
  | "file"
  | "dat_name"
  | "region"
  | "languages"
  | "revision"
  | "flags"
  | "size"
  | "match"
  | "proposed";

export type Column = { id: ColumnId; label: string; sortable: boolean; level: "game" | "version" };

export const COLUMNS: Column[] = [
  { id: "keep", label: "Keep", sortable: false, level: "version" },
  { id: "game", label: "Game", sortable: true, level: "game" },
  { id: "status", label: "Status", sortable: true, level: "game" },
  { id: "versions", label: "Versions", sortable: true, level: "game" },
  { id: "source", label: "Grouped by", sortable: true, level: "game" },
  { id: "file", label: "File", sortable: true, level: "version" },
  { id: "dat_name", label: "DAT name", sortable: true, level: "version" },
  { id: "region", label: "Region", sortable: true, level: "version" },
  { id: "languages", label: "Languages", sortable: true, level: "version" },
  { id: "revision", label: "Revision", sortable: true, level: "version" },
  { id: "flags", label: "Flags", sortable: true, level: "version" },
  { id: "size", label: "Size", sortable: true, level: "version" },
  { id: "match", label: "Match", sortable: true, level: "version" },
  { id: "proposed", label: "Proposed", sortable: true, level: "version" },
];

const IDS = new Set<string>(COLUMNS.map((c) => c.id));

export const SOURCE_LABELS: Record<string, string> = {
  "dat-parent-clone": "DAT parent/clone",
  "retool-clone-list": "Retool clone list",
  "dat-name": "same DAT name",
  single: "—",
};

/** Undecided first: those are the games that need you. */
export const STATUS_ORDER: GameStatus[] = [
  "undecided",
  "your pick",
  "decided",
  "left alone",
  "single",
];

export const COLUMNS_KEY = "g1r.games.columns.v1";
export const WIDTHS_KEY = "g1r.games.widths.v1";

export function loadColumns(defaults: string[]): ColumnId[] {
  const stored = readJson<string[]>(COLUMNS_KEY, defaults, isStringArray).filter((id) =>
    IDS.has(id),
  );
  return (stored.length > 0 ? stored : defaults) as ColumnId[];
}

export function saveColumns(ids: ColumnId[]): void {
  writeJson(COLUMNS_KEY, ids);
}

export type Widths = Partial<Record<ColumnId, number>>;

export function loadWidths(): Widths {
  const stored = readJson<Record<string, number>>(WIDTHS_KEY, {}, isNumberRecord);
  return Object.fromEntries(Object.entries(stored).filter(([id]) => IDS.has(id))) as Widths;
}

export function saveWidths(widths: Widths): void {
  if (Object.keys(widths).length === 0) removeKey(WIDTHS_KEY);
  else writeJson(WIDTHS_KEY, widths);
}

export function widthOf(size: ColumnSize, stored: number | undefined): number {
  return stored === undefined ? size.rem : Math.min(size.max, Math.max(size.min, stored));
}

/** Visible columns in their canonical order; never empty. */
export function visibleColumns(ids: ColumnId[]): Column[] {
  const wanted = new Set(ids);
  const columns = COLUMNS.filter((c) => wanted.has(c.id));
  return columns.length > 0 ? columns : COLUMNS.filter((c) => c.id === "game");
}

export function template(columns: Column[], sizes: Record<string, ColumnSize>, widths: Widths) {
  return columns.map((c) => `${widthOf(sizes[c.id], widths[c.id])}rem`).join(" ");
}

/** The version a game's own row describes: the kept one, else the only one. */
export function representative(game: Game): Version | null {
  return (
    game.versions.find((v) => v.keep) ?? (game.versions.length === 1 ? game.versions[0] : null)
  );
}

export function flagsOf(version: Version): string[] {
  return [
    ...(version.prerelease ? ["pre-release"] : []),
    ...(version.rerelease ? ["re-release"] : []),
    ...version.tags,
  ];
}

type SortValue = string | number;

/** What a game sorts by in a column. Version columns use the representative version. */
export function sortValue(game: Game, id: ColumnId): SortValue {
  const version = representative(game) ?? game.versions[0];
  switch (id) {
    case "game":
      return game.name.toLowerCase();
    case "status":
      return STATUS_ORDER.indexOf(game.status);
    case "versions":
      return game.versions.length;
    case "source":
      return SOURCE_LABELS[game.source] ?? game.source;
    case "file":
      return version.rel_path.toLowerCase();
    case "dat_name":
      return version.game_name.toLowerCase();
    case "region":
      return version.regions.join(", ");
    case "languages":
      return version.languages.join(",");
    case "revision":
      return version.revision ?? "";
    case "flags":
      return flagsOf(version).join(", ");
    case "size":
      return game.versions.reduce((total, v) => total + (v.size ?? 0), 0);
    case "match":
      return version.probability;
    case "proposed":
      return game.versions.filter((v) => v.operation).length;
    default:
      return "";
  }
}

export function sortGames(games: Game[], id: ColumnId | null, order: "asc" | "desc"): Game[] {
  if (id === null) return games;
  const direction = order === "asc" ? 1 : -1;
  return [...games].sort((a, b) => {
    const x = sortValue(a, id);
    const y = sortValue(b, id);
    const result =
      typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
    return result === 0 ? a.name.localeCompare(b.name) : result * direction;
  });
}

export type GameFilter = {
  q: string;
  statuses: GameStatus[];
  several: boolean;
  moves: boolean;
  source: string;
};

export const NO_FILTER: GameFilter = {
  q: "",
  statuses: [],
  several: false,
  moves: false,
  source: "",
};

export function activeFilterCount(filter: GameFilter): number {
  return [filter.statuses.length > 0, filter.several, filter.moves, filter.source !== ""].filter(
    Boolean,
  ).length;
}

export function filterGames(games: Game[], filter: GameFilter): Game[] {
  const needle = filter.q.trim().toLowerCase();
  return games.filter((game) => {
    if (filter.statuses.length > 0 && !filter.statuses.includes(game.status)) return false;
    if (filter.several && game.versions.length <= 1) return false;
    if (filter.moves && !game.versions.some((v) => v.operation)) return false;
    if (filter.source && game.source !== filter.source) return false;
    if (!needle) return true;
    return (
      game.name.toLowerCase().includes(needle) ||
      game.versions.some(
        (v) =>
          v.rel_path.toLowerCase().includes(needle) || v.game_name.toLowerCase().includes(needle),
      )
    );
  });
}
