import {
  Archive,
  ArchiveRestore,
  ArrowRightLeft,
  ChevronRight,
  Circle,
  CircleCheck,
  CircleDashed,
  Copy,
  CornerDownRight,
  EyeOff,
  Globe,
  ListFilter,
  type LucideIcon,
  RotateCcw,
  Search,
  Sparkles,
  Square,
  SquareCheck,
  Trash2,
  UserRound,
} from "lucide-react";
import {
  type CSSProperties,
  type KeyboardEvent,
  type ReactNode,
  useMemo,
  useRef,
  useState,
} from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Pager } from "@/components/Pager";
import { QuickViewBar } from "@/components/QuickViewBar";
import { ColumnChooser, HeaderCell } from "@/components/table/TableParts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { FirstMatch, UnmatchedDetail } from "@/components/unmatched/Unmatched";
import { formatBytes, formatCount, formatFiles } from "@/lib/format";
import type { FileRow, Game, GameStatus, Meta, UnmatchedFile, Version } from "@/lib/types";
import { cn } from "@/lib/utils";
import {
  activeFilterCount,
  COLUMNS,
  type Column,
  type ColumnId,
  convertFirstRow,
  DEFAULT_VIEW,
  defaultSort,
  filterGames,
  filterGamesExceptView,
  flagsOf,
  type GameFilter,
  loadColumns,
  loadWidths,
  methodLabel,
  NO_FILTER,
  QUICK_VIEWS,
  quickView,
  type Row,
  representative,
  SOURCE_LABELS,
  STATUS_ORDER,
  saveColumns,
  saveWidths,
  sortGames,
  template,
  unmatchedRow,
  versionsByFile,
  viewColumns,
  type Widths,
  widthOf,
} from "./columns";

const GRID =
  "grid flex-1 items-center gap-3 [grid-template-columns:var(--games-grid)] *:[contain:inline-size]";

const STATUS_STYLE: Record<GameStatus, string> = {
  undecided: "border-status-warn text-status-warn",
  "your pick": "border-primary text-primary",
  decided: "border-status-good/60 text-status-good",
  "left alone": "border-dashed border-muted-foreground text-muted-foreground",
  single: "border-border text-muted-foreground",
  applied: "border-status-good/60 bg-status-good/10 text-status-good",
  unmatched: "border-dashed border-status-warn text-status-warn",
  "convert first": "border-dashed border-status-convert text-status-convert",
};

/** Files nothing identified, shown as rows of the table, and what can be done with them. */
export type UnmatchedRows = {
  files: UnmatchedFile[];
  busy: boolean;
  onAssign: (relPath: string, game: string) => void;
  /** Review moving the files to discarded/, or deleting them (remove). */
  onMove: (relPaths: string[], remove: boolean) => void;
  /**
   * Shown above the table in the Unmatched view (or while rows are selected): the files it
   * shows, the ones of those selected, and a way to clear the selection.
   */
  tools: (files: UnmatchedFile[], selected: UnmatchedFile[], clear: () => void) => ReactNode;
};

function readFilter(params: URLSearchParams): GameFilter {
  const statuses = (params.get("status") ?? "")
    .split(",")
    .filter((s): s is GameStatus => (STATUS_ORDER as string[]).includes(s));
  return {
    q: params.get("q") ?? "",
    view: quickView(params.get("view") ?? DEFAULT_VIEW).id,
    statuses,
    moves: params.get("moves") === "1",
    source: params.get("source") ?? "",
  };
}

function writeFilter(params: URLSearchParams, filter: GameFilter): URLSearchParams {
  const next = new URLSearchParams(params);
  const set = (key: string, value: string) => (value ? next.set(key, value) : next.delete(key));
  set("q", filter.q);
  set("view", filter.view === DEFAULT_VIEW ? "" : filter.view);
  set("status", filter.statuses.join(","));
  set("moves", filter.moves ? "1" : "");
  set("source", filter.source);
  next.delete("page");
  return next;
}

export function GamesTable({
  label,
  games,
  meta,
  onKeep,
  onLeave,
  onUnassign,
  onApplyGame,
  onRestore,
  unmatched,
  convertFirst,
}: {
  label: string;
  games: Game[];
  meta: Meta;
  onKeep: (game: Game, relPath: string | null) => void;
  onLeave: (game: Game, left: boolean) => void;
  onUnassign?: (version: Version) => void;
  /** Review and apply this game's proposed moves. */
  onApplyGame?: (game: Game) => void;
  /** Move discarded versions back: one version, or every one of a game. */
  onRestore?: (target: { version: Version } | { game: Game }) => void;
  unmatched?: UnmatchedRows;
  /** Files waiting for their conversion: rows of their own, identified once converted. */
  convertFirst?: FileRow[];
}) {
  const [params, setParams] = useSearchParams();
  const filter = useMemo(() => readFilter(params), [params]);
  const sort = (params.get("sort") as ColumnId | null) ?? defaultSort(filter.view);
  const order = params.get("order") === "desc" ? "desc" : "asc";
  const [columnIds, setColumnIds] = useState<ColumnId[]>(() =>
    loadColumns(meta.ui.game_columns_default),
  );
  const [widths, setWidths] = useState<Widths>(loadWidths);
  // Rows opened or closed by hand: games start open, unmatched files start closed.
  const [toggled, setToggled] = useState<Set<string>>(() => new Set());
  // Unmatched files selected (by path), and the row a shift-click range starts from.
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const anchor = useRef<string | null>(null);
  const columns = useMemo(() => {
    const ids = viewColumns(columnIds, filter.view);
    return COLUMNS.filter((c) => ids.includes(c.id));
  }, [columnIds, filter.view]);
  const sizes = meta.ui.game_columns;

  const files = unmatched?.files;
  const rows = useMemo<Row[]>(
    () => [
      ...games,
      ...(files ?? []).map(unmatchedRow),
      ...(convertFirst ?? []).map(convertFirstRow),
    ],
    [games, files, convertFirst],
  );
  const waiting = convertFirst?.length ?? 0;
  const unviewed = useMemo(() => filterGamesExceptView(rows, filter), [rows, filter]);
  const filtered = useMemo(() => filterGames(rows, filter), [rows, filter]);
  const sorted = useMemo(() => sortGames(filtered, sort, order), [filtered, sort, order]);
  const pageSize = meta.ui.page_size;
  const pages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const page = Math.min(pages, Math.max(1, Math.trunc(Number(params.get("page") ?? "1")) || 1));
  const visible = sorted.slice((page - 1) * pageSize, page * pageSize);
  // Only rows shown count as selected, so an action never reaches a file filtered out.
  const shownFiles = useMemo(() => sorted.flatMap((row) => (row.file ? [row.file] : [])), [sorted]);
  const selectedFiles = shownFiles.filter((f) => selected.has(f.rel_path));
  const moves = games.reduce((n, g) => n + g.versions.filter((v) => v.operation).length, 0);
  const reclaim = games.reduce(
    (n, g) => n + g.versions.reduce((m, v) => m + (v.operation ? (v.size ?? 0) : 0), 0),
    0,
  );

  const setFilter = (next: GameFilter) => setParams(writeFilter(params, next), { replace: true });
  const setPage = (next: number) => {
    const p = new URLSearchParams(params);
    p.set("page", String(next));
    setParams(p, { replace: true });
  };
  const onSort = (id: ColumnId) => {
    const p = new URLSearchParams(params);
    if (sort === id) p.set("order", order === "asc" ? "desc" : "asc");
    else {
      p.set("sort", id);
      p.set("order", "asc");
    }
    p.delete("page");
    setParams(p, { replace: true });
  };
  const chooseColumns = (ids: ColumnId[]) => {
    setColumnIds(ids);
    saveColumns(ids);
  };
  const resize = (id: ColumnId, rem: number | null) => {
    setWidths((current) => {
      const next = { ...current };
      if (rem === null) delete next[id];
      else next[id] = rem;
      saveWidths(next);
      return next;
    });
  };
  const clearSelection = () => {
    setSelected(new Set());
    anchor.current = null;
  };
  /** Click selects or unselects one file; shift-click sets a range like the anchor's state. */
  const select = (relPath: string, range: boolean) => {
    const paths = shownFiles.map((f) => f.rel_path);
    // Read now: the state update below runs after the anchor moves to this row.
    const start = anchor.current;
    const from = start === null ? -1 : paths.indexOf(start);
    const to = paths.indexOf(relPath);
    setSelected((current) => {
      const next = new Set(current);
      if (range && start !== null && from >= 0) {
        const on = current.has(start);
        for (const path of paths.slice(Math.min(from, to), Math.max(from, to) + 1)) {
          if (on) next.add(path);
          else next.delete(path);
        }
      } else if (next.has(relPath)) next.delete(relPath);
      else next.add(relPath);
      return next;
    });
    anchor.current = relPath;
  };
  const toggleGame = (key: string) =>
    setToggled((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const style = { "--games-grid": template(columns, sizes, widths) } as CSSProperties;
  const formatSize = (value: number | null) =>
    formatBytes(value, meta.ui.byte_unit_base, meta.ui.byte_units);
  const ctx: CellContext = {
    formatSize,
    onUnassign,
    onRestore,
    onApplyGame,
    label,
    hashLength: meta.ui.hash_display_length,
    unmatched,
  };

  return (
    <div className="space-y-3">
      <QuickViewBar
        name="game-view"
        views={QUICK_VIEWS.map((v) => ({
          id: v.id,
          label: v.label,
          count: unviewed.filter(v.test).length,
        }))}
        value={filter.view}
        onChange={(view) => setFilter({ ...filter, view })}
      />
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-56 flex-1">
          <Search
            className="-translate-y-1/2 absolute top-1/2 left-2.5 size-4 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            aria-label="Search games"
            placeholder="Search games, files, DAT names"
            className="pl-8"
            value={filter.q}
            onChange={(event) => setFilter({ ...filter, q: event.target.value })}
          />
        </div>
        <FilterButton filter={filter} onChange={setFilter} games={rows} />
        <ColumnChooser
          columns={COLUMNS}
          visible={columnIds}
          onChange={(ids) => chooseColumns(ids as ColumnId[])}
          widthsChanged={Object.keys(widths).length > 0}
          onResetWidths={() => {
            setWidths({});
            saveWidths({});
          }}
        />
      </div>
      <p className="text-muted-foreground text-xs">
        {formatCount(sorted.length)} of {formatCount(rows.length)} rows
        {(files && files.length > 0) || waiting > 0
          ? ` (${[
              `${formatCount(games.length)} games`,
              files && files.length > 0 ? `${formatFiles(files.length)} unmatched` : "",
              waiting > 0 ? `${formatFiles(waiting)} to convert first` : "",
            ]
              .filter(Boolean)
              .join(", ")})`
          : ""}
        {moves > 0
          ? ` · ${formatCount(moves)} proposed moves would free ${formatSize(reclaim)}`
          : ""}{" "}
        · click a version to keep it · applying moves the others to discarded/{label}/1g1r/, and
        each move can be restored
      </p>
      {unmatched && (filter.view === "unmatched" || selectedFiles.length > 0)
        ? unmatched.tools(shownFiles, selectedFiles, clearSelection)
        : null}

      <div className="overflow-x-auto rounded-md border border-border bg-card">
        <section style={style} className="min-w-max" aria-label="Games">
          <div className="sticky top-0 z-10 flex items-center border-border border-b bg-card px-3 py-1.5 text-muted-foreground text-xs uppercase tracking-wide">
            <div className={GRID}>
              {columns.map((column) => (
                <HeaderCell
                  key={column.id}
                  id={column.id}
                  label={column.label}
                  sortable={column.sortable}
                  size={sizes[column.id]}
                  width={widthOf(sizes[column.id], widths[column.id])}
                  meta={meta}
                  active={sort === column.id}
                  order={order}
                  onSort={(id) => onSort(id as ColumnId)}
                  onResize={(id, rem) => resize(id as ColumnId, rem)}
                />
              ))}
            </div>
            <span className="w-20 shrink-0" aria-hidden="true" />
          </div>
          {visible.length === 0 ? (
            <p className="px-3 py-6 text-center text-muted-foreground text-sm">No games match.</p>
          ) : (
            visible.map((game) => (
              <GameRows
                key={game.key}
                game={game}
                columns={columns}
                open={game.file ? toggled.has(game.key) : !toggled.has(game.key)}
                onToggle={() => toggleGame(game.key)}
                selected={game.file ? selected.has(game.file.rel_path) : false}
                onSelect={(range) => {
                  if (game.file) select(game.file.rel_path, range);
                }}
                onKeep={onKeep}
                onLeave={onLeave}
                ctx={ctx}
              />
            ))
          )}
        </section>
      </div>

      <Pager page={page} pages={pages} onPage={setPage} />
    </div>
  );
}

function Cell({
  children,
  className,
  title,
}: {
  children?: React.ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <div className={cn("min-w-0 truncate", className)} title={title}>
      {children}
    </div>
  );
}

const PERCENT = new Intl.NumberFormat("en-US", { style: "percent" });

const METHOD_ICONS: Record<string, LucideIcon> = {
  hasheous: Globe,
  duplicate: Copy,
  fuzzy: Sparkles,
  manual: UserRound,
};

function MatchBar({
  version,
  onUnassign,
}: {
  version: Version;
  onUnassign?: (version: Version) => void;
}) {
  const identical =
    version.identical.length > 0 ? ` · identical to ${version.identical.join(", ")}` : "";
  const label = methodLabel(version).long + identical;
  const Icon = METHOD_ICONS[version.method];
  const manual = version.method === "manual" && onUnassign;
  return (
    <span className="flex items-center gap-1.5" title={label}>
      <span className="h-1.5 w-10 shrink-0 overflow-hidden rounded-full bg-muted">
        <span
          className="block h-full w-[calc(var(--p)*100%)] rounded-full bg-primary"
          style={{ "--p": version.probability } as CSSProperties}
        />
      </span>
      <span className="text-muted-foreground text-xs tabular-nums">
        {PERCENT.format(version.probability)}
      </span>
      {manual ? (
        <button
          type="button"
          className="rounded-sm text-primary hover:text-status-bad"
          aria-label={`Unassign ${version.rel_path}`}
          title={`${label} — click to unassign`}
          onClick={(event) => {
            event.stopPropagation();
            onUnassign(version);
          }}
        >
          <UserRound className="size-3" aria-hidden="true" />
        </button>
      ) : Icon ? (
        <Icon className="size-3 shrink-0 text-primary" aria-label={label} />
      ) : null}
    </span>
  );
}

/** What a version's cells need from the table: formatting and the per-version actions. */
type CellContext = {
  formatSize: (v: number | null) => string;
  onUnassign?: (version: Version) => void;
  onRestore?: (target: { version: Version } | { game: Game }) => void;
  onApplyGame?: (game: Game) => void;
  label: string;
  hashLength: number;
  unmatched?: UnmatchedRows;
};

function versionCell(id: ColumnId, version: Version | null, ctx: CellContext) {
  if (version === null) return <Cell key={id} />;
  switch (id) {
    case "file":
      return (
        <Cell key={id} title={version.rel_path}>
          {version.rel_path}
        </Cell>
      );
    case "dat_name":
      return (
        <Cell
          key={id}
          title={
            version.title === version.game_name
              ? version.game_name
              : `${version.title} (set ${version.game_name})`
          }
          className="text-muted-foreground"
        >
          {version.title}
        </Cell>
      );
    case "region":
      return <Cell key={id}>{version.regions.join(", ")}</Cell>;
    case "languages":
      return (
        <Cell key={id} className="text-muted-foreground">
          {version.languages.join(", ")}
        </Cell>
      );
    case "revision":
      return (
        <Cell key={id} className="text-muted-foreground">
          {version.revision ?? ""}
        </Cell>
      );
    case "flags":
      return (
        <Cell key={id} title={flagsOf(version).join(", ")}>
          {flagsOf(version).map((flag) => (
            <Badge key={flag} variant="outline" className="mr-1 font-normal">
              {flag}
            </Badge>
          ))}
        </Cell>
      );
    case "size":
      return (
        <Cell key={id} className="text-right text-muted-foreground tabular-nums">
          {ctx.formatSize(version.size)}
        </Cell>
      );
    case "match":
      if (version.method === "unmatched" || version.method === "convert first") {
        return <Cell key={id} />;
      }
      return (
        <Cell key={id}>
          <MatchBar version={version} onUnassign={ctx.onUnassign} />
        </Cell>
      );
    case "method":
      return (
        <Cell key={id} title={methodLabel(version).long}>
          <span className="text-muted-foreground">{methodLabel(version).short}</span>
        </Cell>
      );
    case "proposed":
      // Not in 1G1R until converted: nothing is proposed for it.
      if (version.method === "convert first") return <Cell key={id} />;
      return (
        <Cell key={id} title={version.operation ?? undefined}>
          {version.discarded ? (
            <span className="inline-flex items-center gap-1 text-muted-foreground">
              in discarded/
              {ctx.onRestore ? (
                <button
                  type="button"
                  className="rounded-sm text-primary hover:underline"
                  aria-label={`Restore ${version.rel_path}`}
                  title="Move it back into the folder"
                  onClick={(event) => {
                    event.stopPropagation();
                    ctx.onRestore?.({ version });
                  }}
                >
                  <ArchiveRestore className="size-3.5" aria-hidden="true" />
                </button>
              ) : null}
            </span>
          ) : version.operation ? (
            <span className="text-status-warn">
              {version.discard_reason === "duplicates"
                ? "→ duplicates"
                : version.discard_reason === "updates"
                  ? "→ updates"
                  : "→ discard"}
            </span>
          ) : version.keep ? (
            <span className="font-medium text-status-good">keep</span>
          ) : (
            <span className="text-muted-foreground">stays</span>
          )}
        </Cell>
      );
    default:
      return <Cell key={id} />;
  }
}

function GameRows({
  game,
  columns,
  open,
  onToggle,
  selected,
  onSelect,
  onKeep,
  onLeave,
  ctx,
}: {
  game: Row;
  columns: Column[];
  open: boolean;
  onToggle: () => void;
  /** Unmatched files only: whether the row is selected, and clicking it (shift: a range). */
  selected: boolean;
  onSelect: (range: boolean) => void;
  onKeep: (game: Game, relPath: string | null) => void;
  onLeave: (game: Game, left: boolean) => void;
  ctx: CellContext;
}) {
  const file = game.file;
  const single = game.versions.length <= 1;
  // A game with several versions opens to them; an unmatched file opens to what is known of it.
  const expandable = !single || file !== undefined;
  const rep = representative(game);
  const left = game.status === "left alone";

  const gameCell = (id: ColumnId) => {
    switch (id) {
      case "keep":
        // A file waiting for its conversion is no version yet: nothing is kept.
        if (game.waiting) return <Cell key={id} />;
        if (file)
          return (
            <Cell key={id}>
              <button
                type="button"
                aria-expanded={open}
                aria-label={`${game.name}: ${open ? "collapse the details" : "show the details"}`}
                title={
                  open ? "Collapse the details" : "Show the details: other names, the DAT search"
                }
                onClick={(event) => {
                  event.stopPropagation();
                  onToggle();
                }}
                className="flex rounded-sm p-0.5 hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring"
              >
                <ChevronRight
                  className={cn(
                    "size-4 text-muted-foreground transition-transform duration-200 motion-reduce:transition-none",
                    open && "rotate-90",
                  )}
                  aria-hidden="true"
                />
              </button>
            </Cell>
          );
        return (
          <Cell key={id}>
            {!expandable ? (
              <CircleCheck className="size-4 text-status-good" aria-label="kept" />
            ) : (
              <ChevronRight
                className={cn(
                  "size-4 text-muted-foreground transition-transform duration-200 motion-reduce:transition-none",
                  open && "rotate-90",
                )}
                aria-hidden="true"
              />
            )}
          </Cell>
        );
      case "game":
        if (file) {
          const Box = selected ? SquareCheck : Square;
          return (
            <Cell key={id} title={game.name} className="flex items-center gap-1.5 font-medium">
              <Box
                className={cn(
                  "size-3.5 shrink-0",
                  selected ? "text-primary" : "text-muted-foreground",
                )}
                aria-hidden="true"
              />
              <span className="min-w-0 truncate">{game.name}</span>
            </Cell>
          );
        }
        return (
          <Cell key={id} title={game.name} className="font-medium">
            {game.name}
          </Cell>
        );
      case "first":
        return <Cell key={id}>{file ? <FirstMatch file={file} /> : null}</Cell>;
      case "status":
        return (
          <Cell key={id}>
            <span
              className={cn("rounded-full border px-2 py-0.5 text-xs", STATUS_STYLE[game.status])}
            >
              {game.status}
            </span>
          </Cell>
        );
      case "versions":
        return (
          <Cell key={id} className="text-muted-foreground tabular-nums">
            {game.versions.length}
          </Cell>
        );
      case "source":
        return (
          <Cell key={id} className="text-muted-foreground text-xs">
            {SOURCE_LABELS[game.source] ?? game.source}
          </Cell>
        );
      case "proposed":
        if (!single && open) return <Cell key={id} />;
        if (!single && game.status === "undecided")
          return (
            <Cell key={id} className="text-status-warn italic">
              choose a version
            </Cell>
          );
        return versionCell(id, rep, ctx);
      default:
        // Open, the versions below say it all; closed, the row is the kept version.
        return versionCell(id, !single && open ? null : rep, ctx);
    }
  };

  return (
    <div
      className={cn(
        "border-border border-b last:border-b-0",
        game.status === "undecided" && "border-l-2 border-l-status-warn",
      )}
    >
      <div
        className={cn(
          "flex items-center px-3 py-1.5 text-sm",
          expandable && "hover:bg-accent/40",
          selected && "bg-primary/10 hover:bg-primary/15",
        )}
      >
        {!expandable ? (
          <div className={GRID}>{columns.map((c) => gameCell(c.id))}</div>
        ) : file ? (
          // biome-ignore lint/a11y/useSemanticElements: a grid row cannot be a <button> (it holds block cells and the chevron button); it is a keyboard-operable toggle.
          <div
            role="button"
            tabIndex={0}
            aria-pressed={selected}
            aria-label={`Select ${game.name}`}
            onClick={(event) => onSelect(event.shiftKey)}
            onKeyDown={(event) => {
              if (event.target !== event.currentTarget) return;
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onSelect(event.shiftKey);
              }
            }}
            className={cn(
              GRID,
              "cursor-pointer select-none rounded-sm focus-visible:outline-2 focus-visible:outline-ring",
            )}
          >
            {columns.map((c) => gameCell(c.id))}
          </div>
        ) : (
          // biome-ignore lint/a11y/useSemanticElements: a grid row cannot be a <button> (it holds block cells); it is a keyboard-operable disclosure.
          <div
            role="button"
            tabIndex={0}
            aria-expanded={open}
            aria-label={`${game.name}: ${open ? "collapse to the kept version" : "show all versions"}`}
            onClick={onToggle}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onToggle();
              }
            }}
            className={cn(
              GRID,
              "cursor-pointer rounded-sm focus-visible:outline-2 focus-visible:outline-ring",
            )}
          >
            {columns.map((c) => gameCell(c.id))}
          </div>
        )}
        <div
          className={cn(
            "sticky right-0 flex w-20 shrink-0 items-center justify-end gap-1 bg-card",
            // Opaque (it scrolls over the cells), in the selected row's tint.
            selected && "bg-[color-mix(in_oklab,var(--color-primary)_10%,var(--color-card))]",
          )}
        >
          {game.waiting ? (
            <Button
              asChild
              variant="ghost"
              size="icon-xs"
              title="Convert it on the Conversion tab: the scan after identifies the result"
              className="text-status-convert"
            >
              <Link to={`/folders/${ctx.label}/conversion`}>
                <ArrowRightLeft className="size-3.5" aria-hidden="true" />
                <span className="sr-only">Convert {game.waiting.rel_path} first</span>
              </Link>
            </Button>
          ) : null}
          {file && ctx.unmatched ? (
            <>
              <Button
                variant="ghost"
                size="icon-xs"
                disabled={ctx.unmatched.busy}
                onClick={() => ctx.unmatched?.onMove([file.rel_path], false)}
                title="Move to discarded/ (can be restored)"
                className="text-status-warn"
              >
                <Archive className="size-3.5" aria-hidden="true" />
                <span className="sr-only">Move {file.rel_path} to discarded</span>
              </Button>
              <Button
                variant="ghost"
                size="icon-xs"
                disabled={ctx.unmatched.busy}
                onClick={() => ctx.unmatched?.onMove([file.rel_path], true)}
                title="Delete for good"
                className="text-status-bad"
              >
                <Trash2 className="size-3.5" aria-hidden="true" />
                <span className="sr-only">Delete {file.rel_path}</span>
              </Button>
            </>
          ) : null}
          {ctx.onApplyGame && game.versions.some((v) => v.operation) ? (
            <Button
              variant="ghost"
              size="icon-xs"
              onClick={() => ctx.onApplyGame?.(game)}
              title="Apply this game: review its moves to discarded/"
              className="text-status-warn"
            >
              <Archive className="size-3.5" aria-hidden="true" />
              <span className="sr-only">Apply {game.name}</span>
            </Button>
          ) : null}
          {ctx.onRestore && game.versions.some((v) => v.discarded) ? (
            <Button
              variant="ghost"
              size="icon-xs"
              onClick={() => ctx.onRestore?.({ game })}
              title="Restore this game: move its discarded versions back"
              className="text-primary"
            >
              <ArchiveRestore className="size-3.5" aria-hidden="true" />
              <span className="sr-only">Restore {game.name}</span>
            </Button>
          ) : null}
          {game.status === "your pick" ? (
            <Button
              variant="ghost"
              size="icon-xs"
              onClick={() => onKeep(game, null)}
              title={`Back to the ranking's choice (${game.reason})`}
            >
              <RotateCcw className="size-3.5" aria-hidden="true" />
              <span className="sr-only">Reset to the ranking's choice</span>
            </Button>
          ) : null}
          {!single ? (
            <Button
              variant="ghost"
              size="icon-xs"
              onClick={() => onLeave(game, !left)}
              title={
                left
                  ? "Include this game in the operations again"
                  : "Take this game out of the operations"
              }
              className={cn(left ? "text-primary" : "text-muted-foreground")}
            >
              <EyeOff className="size-3.5" aria-hidden="true" />
              <span className="sr-only">{left ? "left alone" : "leave alone"}</span>
            </Button>
          ) : null}
        </div>
      </div>
      {file && open && ctx.unmatched ? (
        <div className="border-border border-t border-dashed bg-muted/30 py-2 pr-3 pl-10">
          <UnmatchedDetail
            file={file}
            label={ctx.label}
            hashLength={ctx.hashLength}
            busy={ctx.unmatched.busy}
            onAssign={(name) => ctx.unmatched?.onAssign(file.rel_path, name)}
          />
        </div>
      ) : null}
      {!single && open
        ? versionsByFile(game.versions).map((version) => (
            <VersionRow
              key={version.rel_path}
              game={game}
              version={version}
              columns={columns}
              disabled={left || version.discarded !== null}
              candidate={game.status === "undecided" && game.candidates.includes(version.rel_path)}
              onKeep={onKeep}
              ctx={ctx}
            />
          ))
        : null}
    </div>
  );
}

function VersionRow({
  game,
  version,
  columns,
  disabled,
  candidate,
  onKeep,
  ctx,
}: {
  game: Game;
  version: Version;
  columns: Column[];
  disabled: boolean;
  candidate: boolean;
  onKeep: (game: Game, relPath: string | null) => void;
  ctx: CellContext;
}) {
  // Clicking a version keeps it; clicking your own pick again hands the choice back to the ranking.
  const choose = () => {
    if (disabled) return;
    if (version.keep && game.status === "your pick") onKeep(game, null);
    else if (!version.keep) onKeep(game, version.rel_path);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      choose();
    }
  };
  const cell = (id: ColumnId) => {
    if (id === "keep")
      return (
        <Cell key={id}>
          {version.discarded ? (
            <Archive className="size-4 text-muted-foreground" aria-hidden="true" />
          ) : version.keep ? (
            <CircleCheck className="size-4 text-status-good" aria-hidden="true" />
          ) : candidate ? (
            <CircleDashed className="size-4 text-status-warn" aria-hidden="true" />
          ) : (
            <Circle className="size-4 text-muted-foreground/60" aria-hidden="true" />
          )}
        </Cell>
      );
    if (id === "game")
      return (
        <Cell key={id} className="pl-3 text-muted-foreground">
          <CornerDownRight className="inline size-3.5" aria-hidden="true" />
        </Cell>
      );
    if (id === "status" || id === "versions" || id === "source") return <Cell key={id} />;
    return versionCell(id, version, ctx);
  };
  return (
    // biome-ignore lint/a11y/useSemanticElements: a grid row cannot be a <button> (it holds block cells); it is keyboard-operable.
    <div
      role="button"
      tabIndex={disabled ? -1 : 0}
      aria-pressed={version.keep}
      aria-disabled={disabled}
      onClick={choose}
      onKeyDown={onKeyDown}
      data-testid={`version-${version.rel_path}`}
      title={
        version.discarded
          ? "In discarded/: restore it to keep it"
          : disabled
            ? "This game is left alone"
            : version.keep
              ? "Kept"
              : "Click to keep this version"
      }
      className={cn(
        "flex items-center px-3 py-1 text-sm transition-colors",
        version.keep ? "bg-status-good/10" : "",
        version.discarded ? "text-muted-foreground" : "",
        disabled ? "opacity-60" : "cursor-pointer hover:bg-accent/60",
      )}
    >
      <div className={GRID}>{columns.map((c) => cell(c.id))}</div>
      <span className="w-20 shrink-0" aria-hidden="true" />
    </div>
  );
}

function FilterButton({
  filter,
  onChange,
  games,
}: {
  filter: GameFilter;
  onChange: (next: GameFilter) => void;
  games: Game[];
}) {
  const active = activeFilterCount(filter);
  const counts = useMemo(() => {
    const map = new Map<GameStatus, number>();
    for (const g of games) map.set(g.status, (map.get(g.status) ?? 0) + 1);
    return map;
  }, [games]);
  const sources = useMemo(() => [...new Set(games.map((g) => g.source))].sort(), [games]);
  const toggleStatus = (status: GameStatus) =>
    onChange({
      ...filter,
      statuses: filter.statuses.includes(status)
        ? filter.statuses.filter((s) => s !== status)
        : [...filter.statuses, status],
    });
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" data-testid="filters-button">
          <ListFilter className="size-3.5" aria-hidden="true" /> Filters
          {active > 0 ? <Badge className="ml-1">{active}</Badge> : null}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64" aria-label="Filters">
        <fieldset className="space-y-1.5">
          <legend className="mb-1 text-muted-foreground text-xs">Status</legend>
          {STATUS_ORDER.map((status) => (
            <label key={status} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-3.5 accent-primary"
                checked={filter.statuses.includes(status)}
                onChange={() => toggleStatus(status)}
              />
              <span className="flex-1">{status}</span>
              <span className="text-muted-foreground text-xs tabular-nums">
                {formatCount(counts.get(status) ?? 0)}
              </span>
            </label>
          ))}
        </fieldset>
        <div className="mt-3 space-y-1.5">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="size-3.5 accent-primary"
              checked={filter.moves}
              onChange={() => onChange({ ...filter, moves: !filter.moves })}
            />
            With proposed moves only
          </label>
        </div>
        <label className="mt-3 block text-muted-foreground text-xs">
          Grouped by
          <select
            className="mt-1 h-8 w-full rounded-md border border-input bg-background px-2 text-foreground text-sm"
            value={filter.source}
            onChange={(event) => onChange({ ...filter, source: event.target.value })}
          >
            <option value="">any</option>
            {sources.map((s) => (
              <option key={s} value={s}>
                {SOURCE_LABELS[s] ?? s}
              </option>
            ))}
          </select>
        </label>
        <Button
          variant="ghost"
          size="sm"
          className="mt-3 w-full"
          disabled={active === 0}
          onClick={() => onChange({ ...NO_FILTER, q: filter.q, view: filter.view })}
        >
          Clear filters
        </Button>
      </PopoverContent>
    </Popover>
  );
}
