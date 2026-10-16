import type { Platform } from "./types";

/** Platforms as `[id, profile]` pairs, by display name: every platform list reads this way. */
export function platformsByName(platforms: Record<string, Platform>): [string, Platform][] {
  return Object.entries(platforms).sort(([, a], [, b]) => a.name.localeCompare(b.name));
}
