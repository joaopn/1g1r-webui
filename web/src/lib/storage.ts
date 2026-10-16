/**
 * Browser storage for view preferences (sidebar width, open groups, table columns).
 * Every access is guarded: a private window or blocked site data throws, and a page that
 * cannot render is worse than one that forgets.
 */
function storage(): Storage | undefined {
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}

export function readJson<T>(key: string, fallback: T, valid: (value: unknown) => value is T): T {
  try {
    const raw = storage()?.getItem(key);
    if (!raw) return fallback;
    const parsed: unknown = JSON.parse(raw);
    return valid(parsed) ? parsed : fallback;
  } catch {
    return fallback;
  }
}

export function writeJson(key: string, value: unknown): void {
  try {
    storage()?.setItem(key, JSON.stringify(value));
  } catch {
    // Remembered for this session only.
  }
}

export function removeKey(key: string): void {
  try {
    storage()?.removeItem(key);
  } catch {
    // Nothing to forget.
  }
}

export const isStringArray = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every((item) => typeof item === "string");

export const isNumber = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);

export const isNumberRecord = (value: unknown): value is Record<string, number> =>
  value !== null &&
  typeof value === "object" &&
  !Array.isArray(value) &&
  Object.values(value).every(isNumber);
