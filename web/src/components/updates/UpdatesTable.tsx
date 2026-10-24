import { ArchiveRestore, Check, CornerDownRight } from "lucide-react";
import { useMemo } from "react";
import { flagTone } from "@/components/games/columns";
import {
  type DataColumn,
  DataTable,
  type RowGroup,
  type RowView,
} from "@/components/table/DataTable";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatBytes, formatCount } from "@/lib/format";
import type { Meta, UpdateRow } from "@/lib/types";
import { cn } from "@/lib/utils";

type Row = UpdateRow & { name: string };

const STATUS_WORDS: Record<UpdateRow["status"], string> = {
  newest: "newest, kept",
  older: "older → discard",
  kept: "older, you keep it",
  "version unknown": "version unknown, kept",
  "left alone": "left alone",
  discarded: "in discarded/",
  dlc: "DLC, kept",
};

const STATUS_TONES: Record<UpdateRow["status"], string> = {
  newest: "font-medium text-status-good",
  older: "text-status-warn",
  kept: "text-status-good",
  "version unknown": "text-muted-foreground",
  "left alone": "text-muted-foreground",
  discarded: "text-muted-foreground",
  dlc: "text-status-good",
};

const VIEWS: RowView<Row>[] = [
  { id: "all", label: "All", test: () => true },
  { id: "proposed", label: "To discard", test: (r) => r.status === "older" },
  { id: "kept", label: "Older kept", test: (r) => r.status === "kept" },
  { id: "unknown", label: "Version unknown", test: (r) => r.status === "version unknown" },
  { id: "newer", label: "Newer released", test: (r) => r.newer },
  { id: "dlc", label: "DLC", test: (r) => r.role === "dlc" },
  { id: "discarded", label: "Discarded", test: (r) => r.status === "discarded" },
];

const plural = (n: number, word: string) => `${formatCount(n)} ${word}${n === 1 ? "" : "s"}`;

/** One group per game: its name, then what its rows hold and what is to do. */
const GROUP: RowGroup<Row> = {
  key: (r) => r.group_key,
  name: (rows) => rows[0].game,
  summary: (rows) => {
    const updates = rows.filter((r) => r.role === "update").length;
    const dlc = rows.length - updates;
    const toDiscard = rows.filter((r) => r.status === "older").length;
    return [
      ...(updates ? [plural(updates, "update")] : []),
      ...(dlc ? [`${formatCount(dlc)} DLC`] : []),
      ...(toDiscard ? [`${formatCount(toDiscard)} to discard`] : []),
      ...(rows.some((r) => r.newer) ? ["newer released"] : []),
    ].join(" · ");
  },
  testId: (key) => `updates-game-${key}`,
};

/** The set's updates and DLC, grouped by game (each group opens and closes), updates newest
 * first (the server's order): older ones are proposed for discarded/ unless kept, and a
 * discarded one can be restored. */
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
        // The game heads its group; its rows point to it.
        render: () => (
          <CornerDownRight
            className="ml-3 inline size-3.5 text-muted-foreground"
            aria-hidden="true"
          />
        ),
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
          r.role === "dlc" ? (
            <span className="text-muted-foreground">DLC</span>
          ) : r.release === null ? (
            <span className="text-muted-foreground">unknown</span>
          ) : (
            <span className="tabular-nums">{r.release}</span>
          ),
      },
      {
        id: "latest",
        label: "Latest",
        sortValue: (r) => r.latest_release ?? -1,
        render: (r) =>
          r.latest_release === null ? (
            <span className="text-muted-foreground">–</span>
          ) : (
            <span className={cn("tabular-nums", r.newer && "font-medium text-status-info")}>
              {r.latest_release}
            </span>
          ),
        title: (r) =>
          r.latest_version === null
            ? "titledb knows no update of this game (or titledb is not downloaded)"
            : `The newest update titledb knows: v${r.latest_version}${
                r.latest_date ? `, released ${r.latest_date}` : ""
              }`,
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
        id: "display_version",
        label: "Shown as",
        sortValue: (r) => r.display_version ?? "",
        render: (r) => r.display_version ?? <span className="text-muted-foreground">–</span>,
        title: (r) => (r.display_version ? undefined : "read with prod.keys"),
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
        render: (r) => (
          <span className={STATUS_TONES[r.status]}>
            {STATUS_WORDS[r.status]}
            {r.newer ? (
              <span className="font-normal text-status-info"> · newer released</span>
            ) : null}
          </span>
        ),
        title: (r) =>
          r.newer
            ? `${r.reason}; titledb knows a newer one (update ${r.latest_release}${
                r.latest_date ? `, ${r.latest_date}` : ""
              })`
            : r.reason,
      },
      {
        id: "notes",
        label: "Flags",
        sortValue: (r) => r.notes.join(", "),
        render: (r) =>
          r.notes.map((note) => (
            <Badge key={note} variant="outline" className={cn("mr-1 font-normal", flagTone(note))}>
              {note}
            </Badge>
          )),
        title: (r) => r.notes.join(", ") || undefined,
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
      label="Updates & DLC"
      noun="updates"
      rows={rows}
      rowKey={(r) => r.rel_path}
      rowTestId={(r) => `update-${r.rel_path}`}
      columns={columns}
      sizes={meta.ui.updates_columns}
      defaultColumns={meta.ui.updates_columns_default}
      views={VIEWS}
      group={GROUP}
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
