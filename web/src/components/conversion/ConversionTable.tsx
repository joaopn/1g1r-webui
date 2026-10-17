import { ArrowDown, ArrowRight, ArrowUp, Play, Search, TriangleAlert } from "lucide-react";
import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { Pager } from "@/components/Pager";
import { QuickViewBar } from "@/components/QuickViewBar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatBytes, formatCount } from "@/lib/format";
import type { ConversionRow, ConversionStatus, Meta } from "@/lib/types";
import { cn } from "@/lib/utils";
import {
  CONVERSION_VIEWS,
  type ConversionSort,
  conversionView,
  converting,
  DEFAULT_CONVERSION_VIEW,
  STATUS_LABELS,
  searchRows,
  sortRows,
} from "./rows";

const STATUS_STYLE: Record<ConversionStatus, string> = {
  wrap: "border-primary text-primary",
  unwrap: "border-primary text-primary",
  "make chd": "border-primary text-primary",
  part: "border-border text-muted-foreground",
  flagged: "border-status-warn text-status-warn",
  accepted: "border-border text-muted-foreground",
  done: "border-status-good/60 text-status-good",
};

const SORTS: ConversionSort[] = ["file", "status", "size"];

const HEADERS: { by: ConversionSort | null; label: string; className?: string }[] = [
  { by: "file", label: "File" },
  { by: null, label: "Contains" },
  { by: "status", label: "Proposal" },
  { by: null, label: "Becomes" },
  { by: "size", label: "Size", className: "text-right" },
  { by: null, label: "Original / note" },
  { by: null, label: "" },
];
const DEFAULT_SORT: ConversionSort = "status";

/** Strip the discarded root so the path reads `discarded/<label>/originals/...`. */
function shortDiscarded(path: string, discardedRoot: string): string {
  const parent = discardedRoot.slice(0, discardedRoot.lastIndexOf("/") + 1);
  return path.startsWith(parent) ? path.slice(parent.length) : path;
}

export function ConversionTable({
  rows,
  meta,
  onConvert,
  busy = false,
}: {
  rows: ConversionRow[];
  meta: Meta;
  /** Review and convert one file; the table shows the button only when this is given. */
  onConvert?: (row: ConversionRow) => void;
  busy?: boolean;
}) {
  const [params, setParams] = useSearchParams();
  const view = conversionView(params.get("view") ?? DEFAULT_CONVERSION_VIEW);
  const q = params.get("q") ?? "";
  const sortParam = params.get("sort") as ConversionSort | null;
  const sort = sortParam && SORTS.includes(sortParam) ? sortParam : DEFAULT_SORT;
  const order = params.get("order") === "desc" ? "desc" : "asc";

  const searched = useMemo(() => searchRows(rows, q), [rows, q]);
  const shown = useMemo(
    () => sortRows(searched.filter(view.test), sort, order),
    [searched, view, sort, order],
  );
  const pageSize = meta.ui.page_size;
  const pages = Math.max(1, Math.ceil(shown.length / pageSize));
  const page = Math.min(pages, Math.max(1, Math.trunc(Number(params.get("page") ?? "1")) || 1));
  const visible = shown.slice((page - 1) * pageSize, page * pageSize);

  const update = (changes: Record<string, string>, keepPage = false) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    if (!keepPage) next.delete("page");
    setParams(next, { replace: true });
  };
  const onSort = (by: ConversionSort) =>
    update(
      sort === by
        ? { sort: by, order: order === "asc" ? "desc" : "asc" }
        : { sort: by, order: "asc" },
    );
  const formatSize = (value: number) =>
    formatBytes(value, meta.ui.byte_unit_base, meta.ui.byte_units);

  const header = (by: ConversionSort | null, label: string, className = "") => (
    <th key={label} className={cn("px-3 py-2 font-medium", className)}>
      {by ? (
        <button
          type="button"
          data-testid={`sort-${by}`}
          className="inline-flex items-center gap-1 uppercase hover:text-foreground"
          onClick={() => onSort(by)}
        >
          {label}
          {sort === by ? (
            order === "asc" ? (
              <ArrowUp className="size-3" aria-label="ascending" />
            ) : (
              <ArrowDown className="size-3" aria-label="descending" />
            )
          ) : null}
        </button>
      ) : (
        label
      )}
    </th>
  );

  return (
    <div className="space-y-3">
      <QuickViewBar
        name="conversion-view"
        views={CONVERSION_VIEWS.map((v) => ({
          id: v.id,
          label: v.label,
          count: searched.filter(v.test).length,
        }))}
        value={view.id}
        onChange={(id) => update({ view: id === DEFAULT_CONVERSION_VIEW ? "" : id })}
      />
      <div className="relative">
        <Search
          className="-translate-y-1/2 absolute top-1/2 left-2.5 size-4 text-muted-foreground"
          aria-hidden="true"
        />
        <Input
          aria-label="Search files"
          placeholder="Search files and archive contents"
          className="pl-8"
          value={q}
          onChange={(event) => update({ q: event.target.value })}
        />
      </div>
      <p className="text-muted-foreground text-xs">
        {formatCount(shown.length)} of {formatCount(rows.length)} files
      </p>

      <div className="overflow-x-auto rounded-md border border-border bg-card">
        <table className="w-full min-w-[56rem] table-fixed text-sm">
          <colgroup>
            <col className="w-[26%]" />
            <col className="w-[14%]" />
            <col className="w-[8rem]" />
            <col className="w-[22%]" />
            <col className="w-[6rem]" />
            <col />
            <col className="w-10" />
          </colgroup>
          <thead className="border-border border-b text-left text-muted-foreground text-xs uppercase tracking-wide">
            <tr>{HEADERS.map((h) => header(h.by, h.label, h.className))}</tr>
          </thead>
          <tbody>
            {visible.length === 0 ? (
              <tr>
                <td
                  colSpan={HEADERS.length}
                  className="px-3 py-6 text-center text-muted-foreground"
                >
                  No files match.
                </td>
              </tr>
            ) : (
              visible.map((row) => (
                <tr
                  key={row.rel_path}
                  data-testid={`conversion-${row.rel_path}`}
                  className="border-border border-b last:border-b-0 hover:bg-accent/40"
                >
                  <td className="truncate px-3 py-1.5" title={row.rel_path}>
                    {row.rel_path}
                  </td>
                  <td
                    className="truncate px-3 py-1.5 text-muted-foreground"
                    title={row.members.map((m) => m.name).join("\n")}
                  >
                    {row.container === "plain"
                      ? "bare ROM"
                      : row.members.length === 0
                        ? "—"
                        : row.members.length === 1
                          ? row.members[0].name
                          : `${formatCount(row.members.length)} files`}
                  </td>
                  <td className="px-3 py-1.5">
                    <Badge variant="outline" className={STATUS_STYLE[row.status]}>
                      {STATUS_LABELS[row.status]}
                    </Badge>
                  </td>
                  <td className="truncate px-3 py-1.5" title={row.verify ?? undefined}>
                    {row.output ? (
                      <span className="flex min-w-0 items-center gap-1">
                        <ArrowRight className="size-3 shrink-0 text-primary" aria-hidden="true" />
                        <span className="truncate">{row.output}</span>
                      </span>
                    ) : null}
                  </td>
                  <td className="px-3 py-1.5 text-right text-muted-foreground tabular-nums">
                    {formatSize(row.size)}
                  </td>
                  <td className="px-3 py-1.5 text-muted-foreground">
                    {row.output ? (
                      row.reversible && row.originals_to ? (
                        <span className="block truncate" title={row.originals_to}>
                          → {shortDiscarded(row.originals_to, meta.discarded_root)}
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-status-bad">
                          <TriangleAlert className="size-3" aria-hidden="true" /> deleted
                        </span>
                      )
                    ) : null}
                    {row.note ? <span className="block text-xs">{row.note}</span> : null}
                  </td>
                  <td className="px-1 py-1.5 text-right">
                    {onConvert && converting(row) ? (
                      <Button
                        variant="ghost"
                        size="icon-xs"
                        disabled={busy}
                        onClick={() => onConvert(row)}
                        title="Convert this file: review it first"
                        className="text-primary"
                      >
                        <Play className="size-3.5" aria-hidden="true" />
                        <span className="sr-only">Convert {row.rel_path}</span>
                      </Button>
                    ) : null}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <Pager page={page} pages={pages} onPage={(p) => update({ page: String(p) }, true)} />
    </div>
  );
}
