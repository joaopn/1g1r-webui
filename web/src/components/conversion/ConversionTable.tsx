import { Archive, ArrowRight, Play, TriangleAlert } from "lucide-react";
import { useMemo } from "react";
import { type DataColumn, DataTable, type RowFilter } from "@/components/table/DataTable";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatBytes, formatCount } from "@/lib/format";
import type { ConversionRow, ConversionStatus, Meta } from "@/lib/types";
import { CONVERSION_VIEWS, converting, matchesSearch, STATUS_LABELS, STATUS_ORDER } from "./rows";

const STATUS_STYLE: Record<ConversionStatus, string> = {
  wrap: "border-primary text-primary",
  unwrap: "border-primary text-primary",
  "make chd": "border-primary text-primary",
  "make rvz": "border-primary text-primary",
  byteswap: "border-primary text-primary",
  decrypt: "border-primary text-primary",
  part: "border-border text-muted-foreground",
  flagged: "border-status-warn text-status-warn",
  accepted: "border-border text-muted-foreground",
  done: "border-status-good/60 text-status-good",
};

/** Strip the discarded root so the path reads `discarded/<label>/originals/...`. */
function shortDiscarded(path: string, discardedRoot: string): string {
  const parent = discardedRoot.slice(0, discardedRoot.lastIndexOf("/") + 1);
  return path.startsWith(parent) ? path.slice(parent.length) : path;
}

function contains(row: ConversionRow): string {
  if (row.parts.length > 0) return `track list, ${formatCount(row.parts.length)} track file(s)`;
  if (row.status === "part") return "disc track";
  if (row.container === "plain") return "bare ROM";
  if (row.members.length === 0) return "—";
  if (row.members.length === 1) return row.members[0].name;
  return `${formatCount(row.members.length)} files`;
}

/** Where the original goes: the text a sort and a search see. */
function originalGoes(row: ConversionRow, discardedRoot: string): string {
  if (!row.output) return "";
  return row.reversible && row.originals_to
    ? shortDiscarded(row.originals_to, discardedRoot)
    : "deleted";
}

export function ConversionTable({
  rows,
  meta,
  onConvert,
  onMove,
  busy = false,
}: {
  rows: ConversionRow[];
  meta: Meta;
  /** Review and convert one file; the table shows the button only when this is given. */
  onConvert?: (row: ConversionRow) => void;
  /** Review moving one flagged file to discarded/; shown only when given. */
  onMove?: (row: ConversionRow) => void;
  busy?: boolean;
}) {
  const columns = useMemo<DataColumn<ConversionRow>[]>(() => {
    const formatSize = (value: number) =>
      formatBytes(value, meta.ui.byte_unit_base, meta.ui.byte_units);
    const root = meta.discarded_root;
    return [
      {
        id: "file",
        label: "File",
        sortValue: (r) => r.rel_path.toLowerCase(),
        render: (r) => r.rel_path,
        title: (r) => r.rel_path,
      },
      {
        id: "contains",
        label: "Contains",
        sortValue: (r) => contains(r).toLowerCase(),
        render: (r) => <span className="text-muted-foreground">{contains(r)}</span>,
        title: (r) => r.members.map((m) => m.name).join("\n"),
      },
      {
        id: "container",
        label: "Format",
        sortValue: (r) => r.container,
        render: (r) => <span className="text-muted-foreground">{r.container}</span>,
      },
      {
        id: "status",
        label: "Proposal",
        sortValue: (r) => STATUS_ORDER.indexOf(r.status),
        render: (r) => (
          <Badge variant="outline" className={STATUS_STYLE[r.status]}>
            {STATUS_LABELS[r.status]}
          </Badge>
        ),
      },
      {
        id: "output",
        label: "Becomes",
        sortValue: (r) => (r.output ?? "").toLowerCase(),
        render: (r) =>
          r.output ? (
            <span className="flex min-w-0 items-center gap-1">
              <ArrowRight className="size-3 shrink-0 text-primary" aria-hidden="true" />
              <span className="truncate">{r.output}</span>
            </span>
          ) : null,
        title: (r) => r.verify ?? undefined,
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
        id: "check",
        label: "Check",
        sortValue: (r) => r.verify ?? "",
        render: (r) => <span className="text-muted-foreground">{r.verify ?? ""}</span>,
        title: (r) => r.verify ?? undefined,
      },
      {
        id: "originals",
        label: "Original goes to",
        sortValue: (r) => originalGoes(r, root),
        render: (r) =>
          !r.output ? null : r.reversible && r.originals_to ? (
            <span className="text-muted-foreground">→ {originalGoes(r, root)}</span>
          ) : (
            <span className="inline-flex items-center gap-1 text-status-bad">
              <TriangleAlert className="size-3" aria-hidden="true" /> deleted
            </span>
          ),
        title: (r) => r.originals_to ?? undefined,
      },
      {
        id: "note",
        label: "Note",
        sortValue: (r) => r.note.toLowerCase(),
        render: (r) => <span className="text-muted-foreground text-xs">{r.note}</span>,
        title: (r) => r.note || undefined,
      },
    ];
  }, [meta]);

  const filters = useMemo<RowFilter<ConversionRow>[]>(() => {
    const formats = [...new Set(rows.map((r) => r.container))].sort();
    return [
      {
        id: "status",
        label: "Proposal",
        options: STATUS_ORDER.filter((s) => rows.some((r) => r.status === s)).map((s) => ({
          value: s,
          label: STATUS_LABELS[s],
        })),
        valueOf: (r) => r.status,
      },
      {
        id: "format",
        label: "Format",
        options: formats.map((f) => ({ value: f, label: f })),
        valueOf: (r) => r.container,
      },
      {
        id: "original",
        label: "Original",
        options: [
          { value: "kept", label: "moved to discarded/" },
          { value: "deleted", label: "deleted" },
          { value: "none", label: "no conversion" },
        ],
        valueOf: (r) => (!r.output ? "none" : r.reversible && r.originals_to ? "kept" : "deleted"),
      },
    ];
  }, [rows]);

  return (
    <DataTable
      name="conversion"
      label="Files"
      noun="files"
      rows={rows}
      rowKey={(r) => r.rel_path}
      rowTestId={(r) => `conversion-${r.rel_path}`}
      columns={columns}
      sizes={meta.ui.conversion_columns}
      defaultColumns={meta.ui.conversion_columns_default}
      defaultSort={{ id: "status", order: "asc" }}
      views={CONVERSION_VIEWS}
      search={matchesSearch}
      searchLabel="Search files"
      searchPlaceholder="Search files, archive contents, outputs"
      filters={filters}
      actions={
        onConvert || onMove
          ? (r) =>
              onConvert && converting(r) ? (
                <Button
                  variant="ghost"
                  size="icon-xs"
                  disabled={busy}
                  onClick={() => onConvert(r)}
                  title="Convert this file: review it first"
                  className="text-primary"
                >
                  <Play className="size-3.5" aria-hidden="true" />
                  <span className="sr-only">Convert {r.rel_path}</span>
                </Button>
              ) : onMove && r.status === "flagged" ? (
                <Button
                  variant="ghost"
                  size="icon-xs"
                  disabled={busy}
                  onClick={() => onMove(r)}
                  title="Move this file to discarded/: review it first (can be restored)"
                >
                  <Archive className="size-3.5" aria-hidden="true" />
                  <span className="sr-only">Move {r.rel_path} to discarded/</span>
                </Button>
              ) : null
          : undefined
      }
      meta={meta}
    />
  );
}
