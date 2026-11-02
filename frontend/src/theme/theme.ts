/**
 * Light and dark themes: the system's by default, or the one the owner picks with the toggle.
 *
 * The resolved theme is written to `<html data-theme>`, which the design tokens key on, and to
 * `color-scheme`, so form controls and scrollbars follow. The owner's pick is remembered in local
 * storage; when storage is unavailable (private mode, blocked), the pick still holds for the visit.
 */

export type Theme = "light" | "dark";
export type ThemePreference = Theme | "system";

export const THEME_STORAGE_KEY = "profit-agent.theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";

export function resolveTheme(preference: ThemePreference, systemDark: boolean): Theme {
  if (preference === "system") return systemDark ? "dark" : "light";
  return preference;
}

export function readPreference(storage: Pick<Storage, "getItem"> | null): ThemePreference {
  try {
    const stored = storage?.getItem(THEME_STORAGE_KEY);
    return stored === "light" || stored === "dark" ? stored : "system";
  } catch {
    return "system";
  }
}

export function writePreference(
  storage: Pick<Storage, "setItem" | "removeItem"> | null,
  preference: ThemePreference,
): void {
  try {
    if (preference === "system") storage?.removeItem(THEME_STORAGE_KEY);
    else storage?.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    // Storage refused: the pick still applies until the page is reloaded.
  }
}

export function applyTheme(theme: Theme, root: HTMLElement = document.documentElement): void {
  root.dataset["theme"] = theme;
  root.style.colorScheme = theme;
}

export function systemPrefersDark(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(DARK_QUERY).matches;
}

/** Calls `onChange` when the system theme changes; returns the unsubscribe function. */
export function watchSystemTheme(onChange: (dark: boolean) => void): () => void {
  if (typeof window.matchMedia !== "function") return () => undefined;
  const query = window.matchMedia(DARK_QUERY);
  const listener = (event: MediaQueryListEvent) => {
    onChange(event.matches);
  };
  query.addEventListener("change", listener);
  return () => {
    query.removeEventListener("change", listener);
  };
}

export function safeStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

/** Applies the remembered or system theme before React renders, so the first paint is right. */
export function initTheme(): Theme {
  const theme = resolveTheme(readPreference(safeStorage()), systemPrefersDark());
  applyTheme(theme);
  return theme;
}
