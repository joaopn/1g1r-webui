import type { ConversionRow, ConversionStatus } from "@/lib/types";

/** What needs you first: proposed steps, then flags, then what is fine as it is. */
export const STATUS_ORDER: ConversionStatus[] = [
  "wrap",
  "unwrap",
  "make chd",
  "flagged",
  "part",
  "accepted",
  "done",
];

export const STATUS_LABELS: Record<ConversionStatus, string> = {
  wrap: "zip it",
  unwrap: "unzip it",
  "make chd": "make CHD",
  part: "track",
  flagged: "flagged",
  accepted: "accepted as is",
  done: "done",
};

export type ConversionView = {
  id: string;
  label: string;
  test: (row: ConversionRow) => boolean;
};

export const converting = (row: ConversionRow) =>
  row.status === "wrap" || row.status === "unwrap" || row.status === "make chd";

/** The quick views above the table; add one here and it appears in the bar with its count. */
export const CONVERSION_VIEWS: ConversionView[] = [
  { id: "all", label: "All", test: () => true },
  { id: "convert", label: "To convert", test: converting },
  { id: "flagged", label: "Flagged", test: (r) => r.status === "flagged" },
  { id: "accepted", label: "Accepted as is", test: (r) => r.status === "accepted" },
  { id: "done", label: "Done", test: (r) => r.status === "done" },
];

export const DEFAULT_CONVERSION_VIEW = CONVERSION_VIEWS[0].id;

export function conversionView(id: string): ConversionView {
  return CONVERSION_VIEWS.find((v) => v.id === id) ?? CONVERSION_VIEWS[0];
}

export function searchRows(rows: ConversionRow[], q: string): ConversionRow[] {
  const needle = q.trim().toLowerCase();
  if (!needle) return rows;
  return rows.filter(
    (r) =>
      r.rel_path.toLowerCase().includes(needle) ||
      r.members.some((m) => m.name.toLowerCase().includes(needle)),
  );
}

export type ConversionSort = "file" | "status" | "size";

export function sortRows(
  rows: ConversionRow[],
  by: ConversionSort,
  order: "asc" | "desc",
): ConversionRow[] {
  const direction = order === "asc" ? 1 : -1;
  const value = (r: ConversionRow): string | number =>
    by === "size" ? r.size : by === "status" ? STATUS_ORDER.indexOf(r.status) : r.rel_path;
  return [...rows].sort((a, b) => {
    const x = value(a);
    const y = value(b);
    const result =
      typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
    return result === 0 ? a.rel_path.localeCompare(b.rel_path) : result * direction;
  });
}
