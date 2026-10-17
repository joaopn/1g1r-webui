import { isNumberRecord, isStringArray, readJson, removeKey, writeJson } from "@/lib/storage";
import type { ColumnSize } from "@/lib/types";

/**
 * A table's remembered view, per browser: which columns show and the widths dragged. Each
 * table has its own keys; ids no longer known are dropped on load.
 */
export type Widths = Partial<Record<string, number>>;

export function columnPrefs(name: string, known: string[]) {
  const ids = new Set(known);
  const columnsKey = `g1r.${name}.columns.v1`;
  const widthsKey = `g1r.${name}.widths.v1`;
  return {
    columnsKey,
    widthsKey,
    loadColumns(defaults: string[]): string[] {
      const stored = readJson<string[]>(columnsKey, defaults, isStringArray).filter((id) =>
        ids.has(id),
      );
      return stored.length > 0 ? stored : defaults;
    },
    saveColumns(visible: string[]): void {
      writeJson(columnsKey, visible);
    },
    loadWidths(): Widths {
      const stored = readJson<Record<string, number>>(widthsKey, {}, isNumberRecord);
      return Object.fromEntries(Object.entries(stored).filter(([id]) => ids.has(id)));
    },
    saveWidths(widths: Widths): void {
      if (Object.keys(widths).length === 0) removeKey(widthsKey);
      else writeJson(widthsKey, widths);
    },
  };
}

export function widthOf(size: ColumnSize, stored: number | undefined): number {
  return stored === undefined ? size.rem : Math.min(size.max, Math.max(size.min, stored));
}

/** The CSS grid template of the visible columns, in rem. */
export function template(ids: string[], sizes: Record<string, ColumnSize>, widths: Widths) {
  return ids.map((id) => `${widthOf(sizes[id], widths[id])}rem`).join(" ");
}

/** Sort values: numbers compare as numbers, everything else as text. */
export function compareValues(x: string | number, y: string | number): number {
  return typeof x === "number" && typeof y === "number"
    ? x - y
    : String(x).localeCompare(String(y));
}
