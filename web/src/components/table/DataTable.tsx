import { Search } from "lucide-react";
import { type CSSProperties, type ReactNode, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Pager } from "@/components/Pager";
import { QuickViewBar } from "@/components/QuickViewBar";
import { Input } from "@/components/ui/input";
import { formatCount } from "@/lib/format";
import type { ColumnSize, Meta } from "@/lib/types";
import { cn } from "@/lib/utils";
import { columnPrefs, compareValues, template, type Widths, widthOf } from "./prefs";
import { ColumnChooser, FilterMenu, HeaderCell } from "./TableParts";

/**
 * A flat table with what the Matching table has: quick views, search, filters, sorting by
 * any column, a column chooser and resizable columns (both remembered per browser), and
 * pages. The view lives in the URL (q, view, sort, order, page, f.<filter>), so a reload or a
 * shared link shows the same rows. Widths come from the server's config, like every number.
 */
export type DataColumn<T> = {
  id: string;
  label: string;
  render: (row: T) => ReactNode;
  /** Sortable when given. */
  sortValue?: (row: T) => string | number;
  title?: (row: T) => string | undefined;
  className?: string;
  /** The header's own classes, when not the cells' (`className`). */
  headerClassName?: string;
};

export type RowView<T> = { id: string; label: string; test: (row: T) => boolean };

/** A Filters menu group: rows whose value is one of the checked options. */
export type RowFilter<T> = {
  id: string;
  label: string;
  options: { value: string; label: string }[];
  valueOf: (row: T) => string;
};

const FILTER_PREFIX = "f.";
const ALL_ROWS: RowView<unknown>[] = [{ id: "all", label: "All", test: () => true }];

export function DataTable<T>({
  name,
  label,
  noun,
  rows,
  fit = false,
  rowKey,
  rowTestId,
  columns,
  sizes,
  defaultColumns,
  defaultSort,
  views = ALL_ROWS,
  search,
  searchLabel,
  searchPlaceholder,
  filters = [],
  actions,
  actionsClassName = "w-10",
  note,
  meta,
  paramPrefix = "",
}: {
  /** Names the remembered columns and widths. */
  name: string;
  label: string;
  noun: string;
  rows: T[];
  /** As wide as its columns (a resized column resizes the table), not the full width. */
  fit?: boolean;
  rowKey: (row: T) => string;
  rowTestId?: (row: T) => string;
  columns: DataColumn<T>[];
  sizes: Record<string, ColumnSize>;
  defaultColumns: string[];
  defaultSort?: { id: string; order: "asc" | "desc" };
  /** Quick views; none given shows every row without a views bar. */
  views?: RowView<T>[];
  search: (row: T, needle: string) => boolean;
  searchLabel: string;
  searchPlaceholder: string;
  filters?: RowFilter<T>[];
  /** Per-row buttons, in a column kept at the right edge. */
  actions?: (row: T) => ReactNode;
  actionsClassName?: string;
  note?: ReactNode;
  meta: Meta;
  /** Prefixes the URL parameters, so a second table on the page keeps its own view. */
  paramPrefix?: string;
}) {
  const [urlParams, setParams] = useSearchParams();
  const params = { get: (key: string) => urlParams.get(paramPrefix + key) };
  const prefs = useMemo(
    () =>
      columnPrefs(
        name,
        columns.map((c) => c.id),
      ),
    [name, columns],
  );
  const [columnIds, setColumnIds] = useState<string[]>(() => prefs.loadColumns(defaultColumns));
  const [widths, setWidths] = useState<Widths>(() => prefs.loadWidths());
  const shownColumns = columns.filter((c) => columnIds.includes(c.id));

  const q = params.get("q") ?? "";
  const view = views.find((v) => v.id === params.get("view")) ?? views[0];
  const sortParam = params.get("sort");
  const sortable = (id: string | null) =>
    columns.find((c) => c.id === id && c.sortValue) !== undefined;
  const sort = sortable(sortParam) ? sortParam : (defaultSort?.id ?? null);
  const order =
    params.get("order") === "desc" || (!sortParam && defaultSort?.order === "desc")
      ? "desc"
      : "asc";
  const selected = (id: string) =>
    (params.get(FILTER_PREFIX + id) ?? "").split(",").filter(Boolean);

  const needle = q.trim().toLocaleLowerCase();
  const searched = useMemo(
    () => (needle ? rows.filter((r) => search(r, needle)) : rows),
    [rows, needle, search],
  );
  const passes = (row: T, except: string | null) =>
    filters.every((f) => {
      if (f.id === except) return true;
      const wanted = selected(f.id);
      return wanted.length === 0 || wanted.includes(f.valueOf(row));
    });
  const filtered = searched.filter((r) => passes(r, null));
  const inView = filtered.filter(view.test);
  const sortColumn = columns.find((c) => c.id === sort);
  const sorted = sortColumn?.sortValue
    ? [...inView].sort((a, b) => {
        const value = sortColumn.sortValue as (row: T) => string | number;
        const result = compareValues(value(a), value(b));
        const direction = order === "asc" ? 1 : -1;
        return result === 0 ? rowKey(a).localeCompare(rowKey(b)) : result * direction;
      })
    : inView;
  const pageSize = meta.ui.page_size;
  const pages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const page = Math.min(pages, Math.max(1, Math.trunc(Number(params.get("page") ?? "1")) || 1));
  const visible = sorted.slice((page - 1) * pageSize, page * pageSize);

  const update = (changes: Record<string, string>, keepPage = false) => {
    const next = new URLSearchParams(urlParams);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(paramPrefix + key, value);
      else next.delete(paramPrefix + key);
    }
    if (!keepPage) next.delete(`${paramPrefix}page`);
    setParams(next, { replace: true });
  };
  const onSort = (id: string) =>
    update(
      sort === id
        ? { sort: id, order: order === "asc" ? "desc" : "asc" }
        : { sort: id, order: "asc" },
    );
  const chooseColumns = (ids: string[]) => {
    setColumnIds(ids);
    prefs.saveColumns(ids);
  };
  const resize = (id: string, rem: number | null) =>
    setWidths((current) => {
      const next = { ...current };
      if (rem === null) delete next[id];
      else next[id] = rem;
      prefs.saveWidths(next);
      return next;
    });

  const groups = filters.map((f) => {
    const pool = searched.filter((r) => passes(r, f.id) && view.test(r));
    return {
      id: f.id,
      label: f.label,
      selected: selected(f.id),
      options: f.options.map((o) => ({
        ...o,
        count: pool.filter((r) => f.valueOf(r) === o.value).length,
      })),
    };
  });
  const ids = shownColumns.map((c) => c.id);
  const style = { "--table-grid": template(ids, sizes, widths) } as CSSProperties;
  const grid = "grid items-center gap-3 [grid-template-columns:var(--table-grid)]";

  return (
    <div className={cn("space-y-3", fit && "w-fit max-w-full")}>
      {views === ALL_ROWS ? null : (
        <QuickViewBar
          name={`${name}-view`}
          views={views.map((v) => ({
            id: v.id,
            label: v.label,
            count: filtered.filter(v.test).length,
          }))}
          value={view.id}
          onChange={(id) => update({ view: id === views[0].id ? "" : id })}
        />
      )}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-56 flex-1">
          <Search
            className="-translate-y-1/2 absolute top-1/2 left-2.5 size-4 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            aria-label={searchLabel}
            placeholder={searchPlaceholder}
            className="pl-8"
            value={q}
            onChange={(event) => update({ q: event.target.value })}
          />
        </div>
        {filters.length > 0 ? (
          <FilterMenu
            groups={groups}
            onChange={(id, values) => update({ [FILTER_PREFIX + id]: values.join(",") })}
            onClear={() =>
              update(Object.fromEntries(filters.map((f) => [FILTER_PREFIX + f.id, ""])))
            }
          />
        ) : null}
        <ColumnChooser
          columns={columns}
          visible={columnIds}
          onChange={chooseColumns}
          widthsChanged={Object.keys(widths).length > 0}
          onResetWidths={() => {
            setWidths({});
            prefs.saveWidths({});
          }}
        />
      </div>
      <p className="text-muted-foreground text-xs">
        {formatCount(sorted.length)} of {formatCount(rows.length)} {noun}
        {note ? <> · {note}</> : null}
      </p>

      <div className="overflow-x-auto rounded-md border border-border bg-card">
        <section style={style} className="min-w-max text-sm" aria-label={label}>
          <div className="sticky top-0 z-10 flex items-center border-border border-b bg-card px-3 py-1.5 text-muted-foreground text-xs uppercase tracking-wide">
            <div className={grid}>
              {shownColumns.map((column) => (
                <HeaderCell
                  key={column.id}
                  id={column.id}
                  label={column.label}
                  sortable={column.sortValue !== undefined}
                  size={sizes[column.id]}
                  width={widthOf(sizes[column.id], widths[column.id])}
                  meta={meta}
                  active={sort === column.id}
                  order={order}
                  onSort={onSort}
                  onResize={resize}
                  className={column.headerClassName ?? column.className}
                />
              ))}
            </div>
            {actions ? (
              <span className={cn("shrink-0", actionsClassName)} aria-hidden="true" />
            ) : null}
          </div>
          {visible.length === 0 ? (
            <p className="px-3 py-6 text-center text-muted-foreground">No {noun} match.</p>
          ) : (
            visible.map((row) => (
              <div
                key={rowKey(row)}
                data-testid={rowTestId?.(row)}
                className="flex items-center border-border border-b px-3 py-1.5 last:border-b-0 hover:bg-accent/40"
              >
                <div className={grid}>
                  {shownColumns.map((column) => (
                    <div
                      key={column.id}
                      className={cn("min-w-0 truncate", column.className)}
                      title={column.title?.(row)}
                    >
                      {column.render(row)}
                    </div>
                  ))}
                </div>
                {actions ? (
                  <div
                    className={cn(
                      "sticky right-0 flex shrink-0 items-center justify-end gap-1 bg-card",
                      actionsClassName,
                    )}
                  >
                    {actions(row)}
                  </div>
                ) : null}
              </div>
            ))
          )}
        </section>
      </div>
      <Pager page={page} pages={pages} onPage={(p) => update({ page: String(p) }, true)} />
    </div>
  );
}
