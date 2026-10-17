import {
  Archive,
  ArchiveRestore,
  ArrowDown,
  ArrowUp,
  ChevronRight,
  Circle,
  CircleCheck,
  CircleDashed,
  Columns3,
  CornerDownRight,
  EyeOff,
  Globe,
  ListFilter,
  type LucideIcon,
  RotateCcw,
  Search,
  Sparkles,
  UserRound,
} from "lucide-react";
import { type CSSProperties, type KeyboardEvent, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Pager } from "@/components/Pager";
import { QuickViewBar } from "@/components/QuickViewBar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { formatBytes, formatCount } from "@/lib/format";
import type { Game, GameStatus, Meta, Version } from "@/lib/types";
import { useDragWidth } from "@/lib/useDragWidth";
import { cn } from "@/lib/utils";
import {
  activeFilterCount,
  COLUMNS,
  type Column,
  type ColumnId,
  DEFAULT_VIEW,
  filterGames,
  filterGamesExceptView,
  flagsOf,
  type GameFilter,
  loadColumns,
  loadWidths,
  METHOD_LABELS,
  NO_FILTER,
  QUICK_VIEWS,
  quickView,
  representative,
  SOURCE_LABELS,
  STATUS_ORDER,
  saveColumns,
  saveWidths,
  sortGames,
  template,
  type Widths,
  widthOf,
} from "./columns";

const GRID = "grid items-center gap-3 [grid-template-columns:var(--games-grid)]";

const STATUS_STYLE: Record<GameStatus, string> = {
  undecided: "border-status-warn text-status-warn",
  "your pick": "border-primary text-primary",
  decided: "border-status-good/60 text-status-good",
  "left alone": "border-dashed border-muted-foreground text-muted-foreground",
  single: "border-border text-muted-foreground",
  applied: "border-status-good/60 bg-status-good/10 text-status-good",
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
}) {
  const [params, setParams] = useSearchParams();
  const filter = useMemo(() => readFilter(params), [params]);
  const sort = (params.get("sort") as ColumnId | null) ?? null;
  const order = params.get("order") === "desc" ? "desc" : "asc";
  const [columnIds, setColumnIds] = useState<ColumnId[]>(() =>
    loadColumns(meta.ui.game_columns_default),
  );
  const [widths, setWidths] = useState<Widths>(loadWidths);
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set());
  const columns = useMemo(
    () => COLUMNS.filter((c) => columnIds.includes(c.id)).filter(Boolean),
    [columnIds],
  );
  const sizes = meta.ui.game_columns;

  const unviewed = useMemo(() => filterGamesExceptView(games, filter), [games, filter]);
  const filtered = useMemo(() => filterGames(games, filter), [games, filter]);
  const sorted = useMemo(() => sortGames(filtered, sort, order), [filtered, sort, order]);
  const pageSize = meta.ui.page_size;
  const pages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const page = Math.min(pages, Math.max(1, Math.trunc(Number(params.get("page") ?? "1")) || 1));
  const visible = sorted.slice((page - 1) * pageSize, page * pageSize);
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
  const toggleGame = (key: string) =>
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const style = { "--games-grid": template(columns, sizes, widths) } as CSSProperties;
  const formatSize = (value: number | null) =>
    formatBytes(value, meta.ui.byte_unit_base, meta.ui.byte_units);
  const ctx: CellContext = { formatSize, onUnassign, onRestore, onApplyGame };

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
        <FilterButton filter={filter} onChange={setFilter} games={games} />
        <ColumnChooser
          visible={columnIds}
          onChange={chooseColumns}
          widthsChanged={Object.keys(widths).length > 0}
          onResetWidths={() => {
            setWidths({});
            saveWidths({});
          }}
        />
      </div>
      <p className="text-muted-foreground text-xs">
        {formatCount(sorted.length)} of {formatCount(games.length)} games
        {moves > 0
          ? ` · ${formatCount(moves)} proposed moves would free ${formatSize(reclaim)}`
          : ""}{" "}
        · click a version to keep it · applying moves the others to discarded/{label}/1g1r/, and
        each move can be restored
      </p>

      <div className="overflow-x-auto rounded-md border border-border bg-card">
        <section style={style} className="min-w-max" aria-label="Games">
          <div className="sticky top-0 z-10 flex items-center border-border border-b bg-card px-3 py-1.5 text-muted-foreground text-xs uppercase tracking-wide">
            <div className={GRID}>
              {columns.map((column) => (
                <HeaderCell
                  key={column.id}
                  column={column}
                  width={widthOf(sizes[column.id], widths[column.id])}
                  meta={meta}
                  sort={sort}
                  order={order}
                  onSort={onSort}
                  onResize={resize}
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
                open={!collapsed.has(game.key)}
                onToggle={() => toggleGame(game.key)}
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

function HeaderCell({
  column,
  width,
  meta,
  sort,
  order,
  onSort,
  onResize,
}: {
  column: Column;
  width: number;
  meta: Meta;
  sort: ColumnId | null;
  order: "asc" | "desc";
  onSort: (id: ColumnId) => void;
  onResize: (id: ColumnId, rem: number | null) => void;
}) {
  const size = meta.ui.game_columns[column.id];
  const drag = useDragWidth({
    width,
    min: size.min,
    max: size.max,
    step: meta.ui.resize_step_rem,
    shiftMultiplier: meta.ui.resize_shift_multiplier,
    defaultPx: meta.ui.rem_fallback_px,
    onChange: (rem) => onResize(column.id, rem),
    onReset: () => onResize(column.id, null),
  });
  const active = sort === column.id;
  return (
    <div className="relative min-w-0" data-testid={`header-${column.id}`}>
      {column.sortable ? (
        <button
          type="button"
          onClick={() => onSort(column.id)}
          data-testid={`sort-${column.id}`}
          className={cn(
            "inline-flex max-w-full items-center gap-1 uppercase tracking-wide hover:text-foreground",
            active && "text-foreground",
          )}
        >
          <span className="truncate">{column.label}</span>
          {active ? (
            order === "asc" ? (
              <ArrowUp className="size-3 shrink-0" aria-hidden="true" />
            ) : (
              <ArrowDown className="size-3 shrink-0" aria-hidden="true" />
            )
          ) : null}
        </button>
      ) : (
        <span className="block truncate">{column.label}</span>
      )}
      {/* biome-ignore lint/a11y/useSemanticElements: an <hr> cannot take focus; a focusable separator is the ARIA splitter. */}
      <span
        role="separator"
        aria-orientation="vertical"
        aria-label={`Resize the ${column.label} column`}
        aria-valuenow={width}
        aria-valuemin={size.min}
        aria-valuemax={size.max}
        tabIndex={0}
        title="Drag to resize, double-click to reset"
        data-testid={`resize-${column.id}`}
        className={cn(
          "-right-2 absolute top-0 z-[1] flex h-full w-3 cursor-col-resize touch-none select-none justify-center",
          "after:h-full after:w-px after:bg-border hover:after:bg-foreground/40",
          "focus-visible:outline-none focus-visible:after:w-0.5 focus-visible:after:bg-ring",
        )}
        {...drag}
      />
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
  const label = METHOD_LABELS[version.method]?.long ?? version.method;
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
        <Cell key={id} title={version.game_name} className="text-muted-foreground">
          {version.game_name}
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
      return (
        <Cell key={id}>
          <MatchBar version={version} onUnassign={ctx.onUnassign} />
        </Cell>
      );
    case "method":
      return (
        <Cell key={id} title={METHOD_LABELS[version.method]?.long ?? version.method}>
          <span className="text-muted-foreground">
            {METHOD_LABELS[version.method]?.short ?? version.method}
          </span>
        </Cell>
      );
    case "proposed":
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
            <span className="text-status-warn">→ discard</span>
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
  onKeep,
  onLeave,
  ctx,
}: {
  game: Game;
  columns: Column[];
  open: boolean;
  onToggle: () => void;
  onKeep: (game: Game, relPath: string | null) => void;
  onLeave: (game: Game, left: boolean) => void;
  ctx: CellContext;
}) {
  const single = game.versions.length <= 1;
  const rep = representative(game);
  const left = game.status === "left alone";

  const gameCell = (id: ColumnId) => {
    switch (id) {
      case "keep":
        return (
          <Cell key={id}>
            {single ? (
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
        return (
          <Cell key={id} title={game.name} className="font-medium">
            {game.name}
          </Cell>
        );
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
      <div className={cn("flex items-center px-3 py-1.5 text-sm", !single && "hover:bg-accent/40")}>
        {single ? (
          <div className={GRID}>{columns.map((c) => gameCell(c.id))}</div>
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
        <div className="sticky right-0 flex w-20 shrink-0 items-center justify-end gap-1 bg-card">
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
      {!single && open
        ? game.versions.map((version) => (
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

function ColumnChooser({
  visible,
  onChange,
  widthsChanged,
  onResetWidths,
}: {
  visible: ColumnId[];
  onChange: (next: ColumnId[]) => void;
  widthsChanged: boolean;
  onResetWidths: () => void;
}) {
  const shown = new Set(visible);
  const toggle = (id: ColumnId) => {
    const next = shown.has(id)
      ? visible.filter((v) => v !== id)
      : COLUMNS.map((c) => c.id).filter((v) => shown.has(v) || v === id);
    if (next.length > 0) onChange(next);
  };
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" data-testid="columns-button">
          <Columns3 className="size-3.5" aria-hidden="true" /> Columns
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-52" aria-label="Columns">
        <fieldset className="space-y-1.5">
          <legend className="mb-1 text-muted-foreground text-xs">Columns</legend>
          {COLUMNS.map((column) => (
            <label key={column.id} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-3.5 accent-primary"
                checked={shown.has(column.id)}
                disabled={shown.has(column.id) && visible.length <= 1}
                onChange={() => toggle(column.id)}
                data-testid={`column-${column.id}`}
              />
              {column.label}
            </label>
          ))}
        </fieldset>
        <Button
          variant="ghost"
          size="sm"
          className="mt-3 w-full"
          disabled={!widthsChanged}
          onClick={onResetWidths}
        >
          Reset widths
        </Button>
      </PopoverContent>
    </Popover>
  );
}
