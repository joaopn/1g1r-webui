import { FilePen, Undo2 } from "lucide-react";
import { useMemo } from "react";
import { type DataColumn, DataTable, type RowView } from "@/components/table/DataTable";
import { Button } from "@/components/ui/button";
import { formatBytes } from "@/lib/format";
import type { Meta, RenameRow } from "@/lib/types";
import { cn } from "@/lib/utils";

type Row = RenameRow & { name: string; folder: string };

const baseName = (path: string) => path.split("/").pop() ?? path;
const folderOf = (path: string) => path.split("/").slice(0, -1).join("/");

/** What the Status column says: to rename, named (renamed by the app or already so), or why
 * nothing is proposed. */
function statusOf(r: Row): { text: string; tone: string } {
  if (r.status === "rename") return { text: "to rename", tone: "text-status-info" };
  if (r.status === "named")
    return { text: r.original ? "renamed" : "already named", tone: "text-status-good" };
  return { text: r.reason, tone: "text-muted-foreground" };
}

const VIEWS: RowView<Row>[] = [
  { id: "all", label: "All", test: () => true },
  { id: "rename", label: "To rename", test: (r) => r.status === "rename" },
  { id: "named", label: "Named", test: (r) => r.status === "named" },
  { id: "skipped", label: "Skipped", test: (r) => r.status === "skipped" },
  { id: "renamed", label: "Renamed", test: (r) => r.original !== null },
];

/** Every ROM file of the set: its name now, the one its template proposes (or why none),
 * and the name it had before its first rename. Each row can be renamed on its own, and a
 * renamed one given back its original name. */
export function RenameTable({
  rows: renames,
  meta,
  busy,
  blocked,
  onRename,
  onRevert,
}: {
  rows: RenameRow[];
  meta: Meta;
  busy: boolean;
  /** Renaming waits (files still to convert); reverting never does. */
  blocked: boolean;
  onRename: (relPath: string) => void;
  onRevert: (relPath: string) => void;
}) {
  const rows = useMemo<Row[]>(
    () => renames.map((r) => ({ ...r, name: baseName(r.rel_path), folder: folderOf(r.rel_path) })),
    [renames],
  );
  const columns = useMemo<DataColumn<Row>[]>(() => {
    const formatSize = (value: number) =>
      formatBytes(value, meta.ui.byte_unit_base, meta.ui.byte_units);
    return [
      {
        id: "name",
        label: "File name",
        sortValue: (r) => r.name.toLowerCase(),
        render: (r) => r.name,
        title: (r) => r.rel_path,
      },
      {
        id: "new_name",
        label: "New name",
        sortValue: (r) => (r.new_path ? baseName(r.new_path).toLowerCase() : ""),
        render: (r) =>
          r.new_path ? (
            <span className="text-status-info">{baseName(r.new_path)}</span>
          ) : (
            <span className="text-muted-foreground">—</span>
          ),
        title: (r) => r.new_path ?? undefined,
      },
      {
        id: "original",
        label: "Original name",
        sortValue: (r) => (r.original ? baseName(r.original).toLowerCase() : ""),
        render: (r) =>
          r.original ? <span className="text-muted-foreground">{baseName(r.original)}</span> : null,
        title: (r) => r.original ?? undefined,
      },
      {
        id: "game",
        label: "Identified as",
        sortValue: (r) => (r.game ?? "").toLowerCase(),
        render: (r) => <span className="text-muted-foreground">{r.game ?? ""}</span>,
        title: (r) => r.game ?? undefined,
      },
      {
        id: "folder",
        label: "Folder",
        sortValue: (r) => r.folder.toLowerCase(),
        render: (r) => <span className="text-muted-foreground">{r.folder}</span>,
        title: (r) => r.folder || undefined,
      },
      {
        id: "status",
        label: "Status",
        sortValue: (r) => statusOf(r).text,
        render: (r) => {
          const { text, tone } = statusOf(r);
          return <span className={cn(tone, r.status === "rename" && "font-medium")}>{text}</span>;
        },
        title: (r) => statusOf(r).text,
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
    ];
  }, [meta]);

  return (
    <DataTable
      name="rename"
      label="Rename"
      noun="files"
      rows={rows}
      rowKey={(r) => r.rel_path}
      rowTestId={(r) => `rename-${r.rel_path}`}
      columns={columns}
      sizes={meta.ui.rename_columns}
      defaultColumns={meta.ui.rename_columns_default}
      views={VIEWS}
      search={(r, needle) =>
        [r.rel_path, r.new_path ?? "", r.original ?? "", r.game ?? ""].some((s) =>
          s.toLocaleLowerCase().includes(needle),
        )
      }
      searchLabel="Search files"
      searchPlaceholder="Search file names"
      actionsClassName="w-24"
      actions={(r) =>
        r.status === "rename" ? (
          <Button
            variant="outline"
            size="xs"
            disabled={busy || blocked}
            onClick={() => onRename(r.rel_path)}
            aria-label={`Rename ${r.rel_path}`}
          >
            <FilePen aria-hidden="true" />
            Rename
          </Button>
        ) : r.original !== null ? (
          <Button
            variant="outline"
            size="xs"
            disabled={busy}
            onClick={() => onRevert(r.rel_path)}
            aria-label={`Give ${r.rel_path} back its original name`}
            title={`Back to ${baseName(r.original)}`}
          >
            <Undo2 aria-hidden="true" />
            Revert
          </Button>
        ) : null
      }
      meta={meta}
    />
  );
}
