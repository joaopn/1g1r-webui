import type { ConversionRow, ConversionStatus } from "@/lib/types";

/** What needs you first: proposed steps, then flags, then what is fine as it is. */
export const STATUS_ORDER: ConversionStatus[] = [
  "wrap",
  "unwrap",
  "make chd",
  "make rvz",
  "byteswap",
  "decrypt",
  "flagged",
  "part",
  "accepted",
  "done",
];

export const STATUS_LABELS: Record<ConversionStatus, string> = {
  wrap: "zip it",
  unwrap: "unzip it",
  "make chd": "make CHD",
  "make rvz": "make RVZ",
  byteswap: "fix byte order",
  decrypt: "decrypt",
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
  row.status === "wrap" ||
  row.status === "unwrap" ||
  row.status === "make chd" ||
  row.status === "make rvz" ||
  row.status === "byteswap" ||
  row.status === "decrypt";

/** The quick views above the table; add one here and it appears in the bar with its count. */
export const CONVERSION_VIEWS: ConversionView[] = [
  { id: "all", label: "All", test: () => true },
  { id: "convert", label: "To convert", test: converting },
  { id: "flagged", label: "Flagged", test: (r) => r.status === "flagged" },
  { id: "accepted", label: "Accepted as is", test: (r) => r.status === "accepted" },
  { id: "done", label: "Done", test: (r) => r.status === "done" },
];

/** Search: the file, what it holds, and what it would become. `needle` is lower case. */
export function matchesSearch(row: ConversionRow, needle: string): boolean {
  return (
    row.rel_path.toLowerCase().includes(needle) ||
    (row.output ?? "").toLowerCase().includes(needle) ||
    row.members.some((m) => m.name.toLowerCase().includes(needle))
  );
}
