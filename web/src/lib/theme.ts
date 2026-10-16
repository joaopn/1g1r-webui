/** Light / dark / system, stored per browser; index.html applies it before the first paint. */
export type ThemeChoice = "light" | "dark" | "system";
const KEY = "g1r.theme";

export function readTheme(): ThemeChoice {
  try {
    const stored = window.localStorage.getItem(KEY);
    return stored === "light" || stored === "dark" ? stored : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(choice: ThemeChoice = readTheme()): void {
  const dark =
    choice === "dark" ||
    (choice === "system" && window.matchMedia?.("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", Boolean(dark));
}

export function saveTheme(choice: ThemeChoice): void {
  try {
    if (choice === "system") window.localStorage.removeItem(KEY);
    else window.localStorage.setItem(KEY, choice);
  } catch {
    // Applied for this session only.
  }
  applyTheme(choice);
}
