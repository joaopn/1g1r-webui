/** Sizes in the configured units ("1.4 MiB"); whole bytes stay whole. */
export function formatBytes(
  value: number | null | undefined,
  base: number,
  units: string[],
): string {
  if (value === null || value === undefined) return "";
  let amount = value;
  let index = 0;
  while (amount >= base && index < units.length - 1) {
    amount /= base;
    index += 1;
  }
  return index === 0 ? `${amount} ${units[index]}` : `${amount.toFixed(1)} ${units[index]}`;
}

/** "2026-10-16T19:59:08Z" -> "2026-10-16 19:59 UTC". */
export function formatWhen(value: string | null | undefined): string {
  if (!value) return "";
  const [date, clock] = value.replace(/Z$/, "").split("T");
  if (!clock) return date;
  return `${date} ${clock.split(":").slice(0, -1).join(":")} UTC`;
}

export const formatCount = (value: number) => value.toLocaleString("en-US");
