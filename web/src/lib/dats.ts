import type { Meta } from "@/lib/types";

export type SourceInfo = { label: string; short_label: string; identification_only: boolean };

/** The titledb region file an order entry or a DAT's source names ("US.en"), else null. */
export function titledbFile(meta: Meta, source: string): string | null {
  const prefix = meta.titledb.entry_prefix;
  return source.startsWith(prefix) ? source.slice(prefix.length) : null;
}

/** What to call a DAT's source: a configured source, or a titledb region file. */
export function sourceInfo(meta: Meta, source: string): SourceInfo | undefined {
  const file = titledbFile(meta, source);
  if (file === null) return meta.dat_sources[source];
  return {
    label: `${meta.titledb.label} ${file}`,
    short_label: `${meta.titledb.short_label} ${file}`,
    identification_only: false,
  };
}
