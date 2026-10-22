import { ArchiveRestore, TriangleAlert } from "lucide-react";
import { useMemo } from "react";
import { type DataColumn, DataTable, type RowFilter } from "@/components/table/DataTable";
import { Button } from "@/components/ui/button";
import { formatBytes, formatWhen } from "@/lib/format";
import type { Discarded, DiscardedFile, Meta } from "@/lib/types";

const ALL = "all";
const reasonView = (id: string) => `reason:${id}`;

type Row = DiscardedFile & { reason: string; reasonView: string; name: string };

/** Whether Restore can put a file back, and if not, why. */
type RestoreState = "restorable" | "occupied" | "not-ours" | "unavailable";

const RESTORE_LABELS: Record<RestoreState, string> = {
  restorable: "can be restored",
  occupied: "a file is already there",
  "not-ours": "not moved here by this app",
  unavailable: "folder unavailable",
};

function restoreState(row: Row): RestoreState {
  if (row.restore_to === null) return "unavailable";
  if (row.occupied) return "occupied";
  if (row.operation_id === null) return "not-ours";
  return "restorable";
}

/** discarded/<label>/: one row per file, a quick view per reason, Restore for the app's moves. */
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
  const rows = useMemo<Row[]>(
    () =>
      data.reasons.flatMap((r) =>
        r.files.map((f) => ({
          ...f,
          reason: r.label,
          reasonView: reasonView(r.id),
          name: f.rel_path.split("/").pop() ?? f.rel_path,
        })),
      ),
    [data],
  );
  const views = useMemo(
    () => [
      { id: ALL, label: "All", test: () => true },
      ...data.reasons.map((r) => ({
        id: reasonView(r.id),
        label: r.label,
        test: (row: Row) => row.reasonView === reasonView(r.id),
      })),
    ],
    [data],
  );

  const columns = useMemo<DataColumn<Row>[]>(() => {
    const formatSize = (value: number) =>
      formatBytes(value, meta.ui.byte_unit_base, meta.ui.byte_units);
    return [
      {
        id: "reason",
        label: "Reason",
        sortValue: (r) => r.reason,
        render: (r) => <span className="text-muted-foreground">{r.reason}</span>,
        title: (r) => r.reason,
      },
      {
        id: "name",
        label: "File name",
        sortValue: (r) => r.name.toLowerCase(),
        render: (r) => r.name,
        title: (r) => r.name,
      },
      {
        id: "file",
        label: "Path",
        sortValue: (r) => r.rel_path.toLowerCase(),
        render: (r) => r.rel_path,
        title: (r) => r.rel_path,
      },
      {
        id: "size",
        label: "Size",
        className: "text-right",
        sortValue: (r) => r.size,
        render: (r) => (
          <span className="text-muted-foreground tabular-nums">{formatSize(r.size)}</span>
        ),
      },
      {
        id: "modified",
        label: "File date",
        sortValue: (r) => r.modified,
        render: (r) => (
          <span className="text-muted-foreground tabular-nums">{formatWhen(r.modified)}</span>
        ),
      },
      {
        id: "restore_to",
        label: "Back to",
        sortValue: (r) => r.restore_to ?? "",
        render: (r) => <span className="text-muted-foreground">{r.restore_to ?? ""}</span>,
        title: (r) => r.restore_to ?? undefined,
      },
      {
        id: "restore",
        label: "Restore",
        sortValue: (r) => RESTORE_LABELS[restoreState(r)],
        title: (r) => r.restore_to ?? undefined,
        render: (r) => {
          const state = restoreState(r);
          if (state === "occupied")
            return (
              <span className="inline-flex items-center gap-1 text-status-warn">
                <TriangleAlert className="size-3 shrink-0" aria-hidden="true" />
                {RESTORE_LABELS[state]}
              </span>
            );
          if (state !== "restorable")
            return <span className="text-muted-foreground">{RESTORE_LABELS[state]}</span>;
          return onRestore ? (
            <Button
              variant="outline"
              size="xs"
              disabled={busy}
              onClick={() => r.operation_id !== null && onRestore(r.operation_id)}
              aria-label={`Restore ${r.rel_path}`}
            >
              <ArchiveRestore aria-hidden="true" />
              Restore
            </Button>
          ) : (
            <span className="text-muted-foreground">its old place in the folder (free)</span>
          );
        },
      },
    ];
  }, [meta, onRestore, busy]);

  const filters = useMemo<RowFilter<Row>[]>(
    () => [
      {
        id: "restore",
        label: "Restore",
        options: (Object.keys(RESTORE_LABELS) as RestoreState[]).map((s) => ({
          value: s,
          label: RESTORE_LABELS[s],
        })),
        valueOf: restoreState,
      },
    ],
    [],
  );

  return (
    <DataTable
      name="discarded"
      label="Discarded files"
      noun="files"
      rows={rows}
      rowKey={(r) => `${r.reasonView}/${r.rel_path}`}
      rowTestId={(r) => `discarded-${r.rel_path}`}
      columns={columns}
      sizes={meta.ui.discarded_columns}
      defaultColumns={meta.ui.discarded_columns_default}
      views={views}
      search={(r, needle) => r.rel_path.toLocaleLowerCase().includes(needle)}
      searchLabel="Search files"
      searchPlaceholder="Search discarded files"
      filters={filters}
      meta={meta}
    />
  );
}
