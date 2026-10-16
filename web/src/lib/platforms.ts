import type { Platform } from "./types";

/** Platforms as `[id, profile]` pairs, by display name: every platform list reads this way. */
export function platformsByName(platforms: Record<string, Platform>): [string, Platform][] {
  return Object.entries(platforms).sort(([, a], [, b]) => a.name.localeCompare(b.name));
}

/** Folders by their platform's display name, then by label. */
export function foldersByName<F extends { platform: string; label: string }>(
  folders: F[],
  platforms: Record<string, Platform> | undefined,
): F[] {
  const name = (folder: F) => platforms?.[folder.platform]?.name ?? folder.platform;
  return [...folders].sort(
    (a, b) => name(a).localeCompare(name(b)) || a.label.localeCompare(b.label),
  );
}
