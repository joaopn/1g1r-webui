import { ArchiveRestore, Check } from "lucide-react";
import { useMemo } from "react";
import { type DataColumn, DataTable, type RowView } from "@/components/table/DataTable";
import { Button } from "@/components/ui/button";
import { formatBytes } from "@/lib/format";
import type { Meta, UpdateRow } from "@/lib/types";

type Row = UpdateRow & { name: string };

const STATUS_WORDS: Record<UpdateRow["status"], string> = {
  newest: "newest, kept",
  older: "older → discard",
  kept: "older, you keep it",
  "version unknown": "version unknown, kept",
  "left alone": "left alone",
  discarded: "in discarded/",
};

const STATUS_TONES: Record<UpdateRow["status"], string> = {
  newest: "font-medium text-status-good",
  older: "text-status-warn",
  kept: "text-status-good",
  "version unknown": "text-muted-foreground",
  "left alone": "text-muted-foreground",
  discarded: "text-muted-foreground",
};

const VIEWS: RowView<Row>[] = [
  { id: "all", label: "All", test: () => true },
  { id: "proposed", label: "To discard", test: (r) => r.status === "older" },
  { id: "kept", label: "Older kept", test: (r) => r.status === "kept" },
  { id: "unknown", label: "Version unknown", test: (r) => r.status === "version unknown" },
  { id: "discarded", label: "Discarded", test: (r) => r.status === "discarded" },
];

/** The set's updates, by game and newest first (the server's order): older ones are proposed
 * for discarded/ unless kept, and a discarded one can be restored. */
export function UpdatesTable({
  updates,
  meta,
  busy,
  onKeep,
  onRestore,
}: {
  updates: UpdateRow[];
  meta: Meta;
  busy: boolean;
  onKeep: (relPath: string, keep: boolean) => void;
  onRestore: (operationId: number) => void;
}) {
  const rows = useMemo<Row[]>(
    () => updates.map((u) => ({ ...u, name: u.rel_path.split("/").pop() ?? u.rel_path })),
    [updates],
  );
  const columns = useMemo<DataColumn<Row>[]>(
    () => [
      {
        id: "game",
        label: "Game",
        sortValue: (r) => r.game.toLowerCase(),
        render: (r) => r.game,
        title: (r) => r.game,
      },
      {
        id: "name",
        label: "File name",
        sortValue: (r) => r.name.toLowerCase(),
        render: (r) => r.name,
        title: (r) => r.rel_path,
      },
      {
        id: "release",
        label: "Update",
        sortValue: (r) => r.release ?? -1,
        render: (r) =>
          r.release === null ? (
            <span className="text-muted-foreground">unknown</span>
          ) : (
            <span className="tabular-nums">{r.release}</span>
          ),
      },
      {
        id: "version",
        label: "Version",
        sortValue: (r) => r.version ?? -1,
        render: (r) => (
          <span className="text-muted-foreground tabular-nums">
            {r.version === null ? "" : `v${r.version}`}
          </span>
        ),
      },
      {
        id: "title_id",
        label: "Title ID",
        sortValue: (r) => r.title_id,
        render: (r) => <code className="text-xs">{r.title_id}</code>,
      },
      {
        id: "status",
        label: "Status",
        sortValue: (r) => STATUS_WORDS[r.status],
        render: (r) => <span className={STATUS_TONES[r.status]}>{STATUS_WORDS[r.status]}</span>,
        title: (r) => r.reason,
      },
      {
        id: "size",
        label: "Size",
        className: "text-right",
        sortValue: (r) => r.size ?? 0,
        render: (r) => (
          <span className="text-muted-foreground tabular-nums">
            {r.size === null ? "" : formatBytes(r.size, meta.ui.byte_unit_base, meta.ui.byte_units)}
          </span>
        ),
      },
    ],
    [meta],
  );
  const actions = (r: Row) => {
    if (r.status === "older" || r.status === "kept") {
      const kept = r.status === "kept";
      return (
        <Button
          variant={kept ? "secondary" : "outline"}
          size="xs"
          disabled={busy}
          aria-pressed={kept}
          aria-label={`Keep ${r.rel_path}`}
          onClick={() => onKeep(r.rel_path, !kept)}
        >
          {kept ? <Check aria-hidden="true" /> : null}
          Keep
        </Button>
      );
    }
    if (r.status === "discarded" && r.discarded !== null) {
      const id = r.discarded;
      return (
        <Button
          variant="outline"
          size="xs"
          disabled={busy}
          aria-label={`Restore ${r.rel_path}`}
          onClick={() => onRestore(id)}
        >
          <ArchiveRestore aria-hidden="true" />
          Restore
        </Button>
      );
    }
    return null;
  };
  return (
    <DataTable
      name="updates"
      label="Updates"
      noun="updates"
      rows={rows}
      rowKey={(r) => r.rel_path}
      rowTestId={(r) => `update-${r.rel_path}`}
      columns={columns}
      sizes={meta.ui.updates_columns}
      defaultColumns={meta.ui.updates_columns_default}
      views={VIEWS}
      search={(r, needle) =>
        r.rel_path.toLocaleLowerCase().includes(needle) ||
        r.game.toLocaleLowerCase().includes(needle)
      }
      searchLabel="Search updates"
      searchPlaceholder="Search games and files"
      actions={actions}
      actionsClassName="w-24"
      meta={meta}
    />
  );
}
