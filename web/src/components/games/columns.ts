import {
  columnPrefs,
  type Widths as TableWidths,
  template as tableTemplate,
  widthOf,
} from "@/components/table/prefs";
import type { ColumnSize, Game, GameStatus, UnmatchedFile, Version } from "@/lib/types";

export { widthOf };

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
  | "method"
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
  { id: "method", label: "Matched by", sortable: true, level: "version" },
  { id: "proposed", label: "Proposed", sortable: true, level: "version" },
];

export const SOURCE_LABELS: Record<string, string> = {
  "dat-parent-clone": "DAT parent/clone",
  "retool-clone-list": "Retool clone list",
  "dat-name": "same DAT name",
  "title-id": "title ID",
  single: "—",
};

/** How a version was identified, short for the table and long for its tooltip. */
export const METHOD_LABELS: Record<string, { short: string; long: string }> = {
  "dat-checksum": { short: "DAT", long: "checksum match in the DAT" },
  "dat-headerless": {
    short: "DAT, no header",
    long: "checksum match in the DAT after removing a copier header",
  },
  "dat-byteswapped": {
    short: "DAT, byte order",
    long: "checksum match in the DAT after putting the ROM in its native byte order",
  },
  "dat-untrimmed": {
    short: "DAT, trimmed",
    long: "checksum match in the DAT after padding the trimmed card image back to its size",
  },
  "title-id": {
    short: "title ID",
    long: "identified by its title ID (from its ticket or its file name), without a DAT",
  },
  duplicate: {
    short: "copy",
    long: "byte-identical to another file of this game, which the DAT identified",
  },
  hasheous: { short: "Hasheous", long: "checksum match found by Hasheous" },
  fuzzy: { short: "name", long: "name match above your auto-match threshold" },
  manual: { short: "by you", long: "assigned by you" },
  unmatched: {
    short: "unmatched",
    long: "nothing identified this file: open the row to say what it is",
  },
};

/** A table row: a game, or a file nothing identified (which carries what is known of it). */
export type Row = Game & { file?: UnmatchedFile };

/** An unmatched file as a one-version row, named after its file, so it sorts and filters in. */
export function unmatchedRow(file: UnmatchedFile): Row {
  const base = file.rel_path.split("/").pop() ?? file.rel_path;
  return {
    key: `unmatched:${file.rel_path}`,
    name: base.replace(/\.[^.]+$/, "") || base,
    source: "single",
    status: "unmatched",
    reason: "",
    kept: null,
    candidates: [],
    file,
    versions: [
      {
        rel_path: file.rel_path,
        game_name: "",
        title: "",
        method: "unmatched",
        dat: null,
        probability: 0,
        regions: [],
        languages: [],
        revision: null,
        prerelease: false,
        rerelease: false,
        tags: [],
        size: file.size,
        keep: false,
        operation: null,
        discarded: null,
        identical: [],
        notes: [],
        role: null,
        discard_reason: null,
      },
    ],
  };
}

/**
 * How a version was identified, naming its DAT: "No-Intro", "libretro, no header" in the
 * table; the DAT's source, name and version in the tooltip.
 */
export function methodLabel(version: Version): { short: string; long: string } {
  const known = METHOD_LABELS[version.method] ?? { short: version.method, long: version.method };
  const dat = version.dat;
  if (!dat) return known;
  const which = `${dat.source_label}: ${dat.header_name}${dat.version ? ` (${dat.version})` : ""}`;
  return {
    short: version.method.startsWith("dat-") ? known.short.replace(/^DAT/, dat.label) : known.short,
    long: `${known.long} · ${which}`,
  };
}

/** Undecided first: those are the games that need you. */
export const STATUS_ORDER: GameStatus[] = [
  "undecided",
  "unmatched",
  "your pick",
  "decided",
  "left alone",
  "applied",
  "single",
];

const PREFS = columnPrefs(
  "games",
  COLUMNS.map((c) => c.id),
);
export const COLUMNS_KEY = PREFS.columnsKey;
export const WIDTHS_KEY = PREFS.widthsKey;

export function loadColumns(defaults: string[]): ColumnId[] {
  return PREFS.loadColumns(defaults) as ColumnId[];
}

export function saveColumns(ids: ColumnId[]): void {
  PREFS.saveColumns(ids);
}

export type Widths = TableWidths;

export function loadWidths(): Widths {
  return PREFS.loadWidths();
}

export function saveWidths(widths: Widths): void {
  PREFS.saveWidths(widths);
}

/** Visible columns in their canonical order; never empty. */
export function visibleColumns(ids: ColumnId[]): Column[] {
  const wanted = new Set(ids);
  const columns = COLUMNS.filter((c) => wanted.has(c.id));
  return columns.length > 0 ? columns : COLUMNS.filter((c) => c.id === "game");
}

export function template(columns: Column[], sizes: Record<string, ColumnSize>, widths: Widths) {
  return tableTemplate(
    columns.map((c) => c.id),
    sizes,
    widths,
  );
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
    ...version.notes,
    ...(version.role === "dlc" ? ["DLC"] : version.role === "update" ? ["update"] : []),
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
      return version.title.toLowerCase();
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
    case "method":
      return methodLabel(version).short;
    case "proposed":
      return game.versions.filter((v) => v.operation).length;
    default:
      return "";
  }
}

export function sortGames<T extends Game>(
  games: T[],
  id: ColumnId | null,
  order: "asc" | "desc",
): T[] {
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

/**
 * The quick-filter bar above the table: one view at a time, for the common cuts. Add a view
 * here and it appears in the bar, with its count.
 */
export type QuickView = { id: string; label: string; test: (game: Game) => boolean };

export const QUICK_VIEWS: QuickView[] = [
  { id: "all", label: "All", test: () => true },
  {
    id: "one",
    label: "One version",
    test: (g) => g.versions.length === 1 && g.status !== "unmatched",
  },
  { id: "several", label: "Several versions", test: (g) => g.versions.length > 1 },
  {
    id: "unmatched",
    label: "Unmatched",
    test: (g) => g.versions.some((v) => v.method === "unmatched"),
  },
  { id: "to-apply", label: "To apply", test: (g) => g.versions.some((v) => v.operation) },
  { id: "applied", label: "Applied", test: (g) => g.versions.some((v) => v.discarded) },
];

export const DEFAULT_VIEW = QUICK_VIEWS[0].id;

export function quickView(id: string): QuickView {
  return QUICK_VIEWS.find((v) => v.id === id) ?? QUICK_VIEWS[0];
}

export type GameFilter = {
  q: string;
  view: string;
  statuses: GameStatus[];
  moves: boolean;
  source: string;
};

export const NO_FILTER: GameFilter = {
  q: "",
  view: DEFAULT_VIEW,
  statuses: [],
  moves: false,
  source: "",
};

/** Filters set in the popover; the quick view and the search show on their own. */
export function activeFilterCount(filter: GameFilter): number {
  return [filter.statuses.length > 0, filter.moves, filter.source !== ""].filter(Boolean).length;
}

/** Every filter but the quick view, so the bar can count what each view would show. */
export function filterGamesExceptView<T extends Game>(games: T[], filter: GameFilter): T[] {
  return filterGames(games, { ...filter, view: DEFAULT_VIEW });
}

export function filterGames<T extends Game>(games: T[], filter: GameFilter): T[] {
  const needle = filter.q.trim().toLowerCase();
  const view = quickView(filter.view);
  return games.filter((game) => {
    if (!view.test(game)) return false;
    if (filter.statuses.length > 0 && !filter.statuses.includes(game.status)) return false;
    if (filter.moves && !game.versions.some((v) => v.operation)) return false;
    if (filter.source && game.source !== filter.source) return false;
    if (!needle) return true;
    return (
      game.name.toLowerCase().includes(needle) ||
      game.versions.some(
        (v) =>
          v.rel_path.toLowerCase().includes(needle) ||
          v.game_name.toLowerCase().includes(needle) ||
          v.title.toLowerCase().includes(needle),
      )
    );
  });
}
