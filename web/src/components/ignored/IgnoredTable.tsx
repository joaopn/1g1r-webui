import { useMemo } from "react";
import { type DataColumn, DataTable } from "@/components/table/DataTable";
import { formatBytes } from "@/lib/format";
import type { Meta, OtherFile } from "@/lib/types";

type Row = OtherFile & { name: string; by: string };

/** What an ignore entry is called in the table. */
function byText(by: string | null): string {
  if (by === "file") return "this file";
  if (by === "hidden") return "hidden file";
  return by ?? "nothing now (next check)";
}

/** The files the set's ignore list leaves out, as the last check found them. */
export function IgnoredTable({ files, meta }: { files: OtherFile[]; meta: Meta }) {
  const rows = useMemo<Row[]>(
    () =>
      files.map((f) => ({
        ...f,
        name: f.rel_path.split("/").pop() ?? f.rel_path,
        by: byText(f.ignored_by),
      })),
    [files],
  );
  const columns = useMemo<DataColumn<Row>[]>(
    () => [
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
          <span className="text-muted-foreground tabular-nums">
            {formatBytes(r.size, meta.ui.byte_unit_base, meta.ui.byte_units)}
          </span>
        ),
      },
      {
        id: "ignored_by",
        label: "Ignored by",
        sortValue: (r) => r.by,
        render: (r) =>
          r.ignored_by && r.ignored_by !== "file" && r.ignored_by !== "hidden" ? (
            <code className="text-xs">{r.by}</code>
          ) : (
            <span className="text-muted-foreground">{r.by}</span>
          ),
        title: (r) => r.by,
      },
    ],
    [meta],
  );
  return (
    <DataTable
      name="ignored"
      label="Ignored files"
      noun="files"
      rows={rows}
      rowKey={(r) => r.rel_path}
      rowTestId={(r) => `ignored-${r.rel_path}`}
      columns={columns}
      sizes={meta.ui.ignored_columns}
      defaultColumns={meta.ui.ignored_columns_default}
      search={(r, needle) => r.rel_path.toLocaleLowerCase().includes(needle)}
      searchLabel="Search files"
      searchPlaceholder="Search ignored files"
      meta={meta}
    />
  );
}
