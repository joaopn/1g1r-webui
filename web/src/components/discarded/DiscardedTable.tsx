import { ArchiveRestore, Search, TriangleAlert } from "lucide-react";
import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { Pager } from "@/components/Pager";
import { QuickViewBar } from "@/components/QuickViewBar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatBytes, formatCount, formatWhen } from "@/lib/format";
import type { Discarded, DiscardedFile, Meta } from "@/lib/types";

const ALL = "all";
const reasonView = (id: string) => `reason:${id}`;

type Row = DiscardedFile & { reason: string; reasonView: string };

const HEADERS = ["Reason", "File", "Size", "File date", "Restores to"];

/** Read-only listing of discarded/<label>/: one row per file, a quick view per reason. */
export function DiscardedTable({
  data,
  meta,
  onRestore,
  busy = false,
}: {
  data: Discarded;
  meta: Meta;
  /** Move one file back (by the apply operation that moved it); absent = read-only. */
  onRestore?: (operationId: number) => void;
  busy?: boolean;
}) {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const rows = useMemo<Row[]>(
    () =>
      data.reasons.flatMap((r) =>
        r.files.map((f) => ({ ...f, reason: r.label, reasonView: reasonView(r.id) })),
      ),
    [data],
  );
  const views = [
    { id: ALL, label: "All", test: () => true },
    ...data.reasons.map((r) => ({
      id: reasonView(r.id),
      label: r.label,
      test: (row: Row) => row.reasonView === reasonView(r.id),
    })),
  ];
  const view = views.find((v) => v.id === params.get("view")) ?? views[0];
  const needle = q.trim().toLocaleLowerCase();
  const searched = needle
    ? rows.filter((r) => r.rel_path.toLocaleLowerCase().includes(needle))
    : rows;
  const shown = searched.filter(view.test);
  const pageSize = meta.ui.page_size;
  const pages = Math.max(1, Math.ceil(shown.length / pageSize));
  const page = Math.min(pages, Math.max(1, Math.trunc(Number(params.get("page") ?? "1")) || 1));
  const visible = shown.slice((page - 1) * pageSize, page * pageSize);
  const formatSize = (value: number) =>
    formatBytes(value, meta.ui.byte_unit_base, meta.ui.byte_units);

  const update = (changes: Record<string, string>, keepPage = false) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    if (!keepPage) next.delete("page");
    setParams(next, { replace: true });
  };

  return (
    <div className="space-y-3">
      <QuickViewBar
        name="discarded-view"
        views={views.map((v) => ({
          id: v.id,
          label: v.label,
          count: searched.filter(v.test).length,
        }))}
        value={view.id}
        onChange={(id) => update({ view: id === ALL ? "" : id })}
      />
      <div className="relative">
        <Search
          className="-translate-y-1/2 absolute top-1/2 left-2.5 size-4 text-muted-foreground"
          aria-hidden="true"
        />
        <Input
          aria-label="Search files"
          placeholder="Search discarded files"
          className="pl-8"
          value={q}
          onChange={(event) => update({ q: event.target.value })}
        />
      </div>
      <p className="text-muted-foreground text-xs">
        {formatCount(shown.length)} of {formatCount(rows.length)} files
      </p>
      <div className="overflow-x-auto rounded-md border border-border bg-card">
        <table className="w-full min-w-[48rem] table-fixed text-sm">
          <colgroup>
            <col className="w-[8rem]" />
            <col className="w-[34%]" />
            <col className="w-[6rem]" />
            <col className="w-[11.5rem]" />
            <col />
          </colgroup>
          <thead className="border-border border-b text-left text-muted-foreground text-xs uppercase tracking-wide">
            <tr>
              {HEADERS.map((h) => (
                <th
                  key={h}
                  className={
                    h === "Size" ? "px-3 py-2 text-right font-medium" : "px-3 py-2 font-medium"
                  }
                >
                  {h}
                </th>
              ))}
            </tr>
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
                  key={`${row.reasonView}/${row.rel_path}`}
                  data-testid={`discarded-${row.rel_path}`}
                  className="border-border border-b last:border-b-0 hover:bg-accent/40"
                >
                  <td className="truncate px-3 py-1.5 text-muted-foreground" title={row.reason}>
                    {row.reason}
                  </td>
                  <td className="truncate px-3 py-1.5" title={row.rel_path}>
                    {row.rel_path}
                  </td>
                  <td className="px-3 py-1.5 text-right text-muted-foreground tabular-nums">
                    {formatSize(row.size)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-1.5 text-muted-foreground tabular-nums">
                    {formatWhen(row.modified)}
                  </td>
                  <td className="truncate px-3 py-1.5" title={row.restore_to ?? undefined}>
                    {row.restore_to === null ? (
                      <span className="text-muted-foreground">folder unavailable</span>
                    ) : row.occupied ? (
                      <span className="inline-flex items-center gap-1 text-status-warn">
                        <TriangleAlert className="size-3 shrink-0" aria-hidden="true" />a file is
                        already there
                      </span>
                    ) : row.operation_id === null ? (
                      <span className="text-muted-foreground">not moved here by this app</span>
                    ) : onRestore ? (
                      <Button
                        variant="outline"
                        size="xs"
                        disabled={busy}
                        onClick={() => row.operation_id !== null && onRestore(row.operation_id)}
                        aria-label={`Restore ${row.rel_path}`}
                      >
                        <ArchiveRestore aria-hidden="true" />
                        Restore
                      </Button>
                    ) : (
                      <span className="text-muted-foreground">
                        its old place in the folder (free)
                      </span>
                    )}
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
