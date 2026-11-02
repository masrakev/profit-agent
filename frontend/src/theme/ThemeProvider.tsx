import { useEffect, useMemo, useState, type ReactNode } from "react";

import { ThemeContext, type ThemeState } from "./context";
import {
  applyTheme,
  readPreference,
  resolveTheme,
  safeStorage,
  systemPrefersDark,
  watchSystemTheme,
  writePreference,
  type ThemePreference,
} from "./theme";

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(() =>
    readPreference(safeStorage()),
  );
  const [systemDark, setSystemDark] = useState(systemPrefersDark);
  const theme = resolveTheme(preference, systemDark);

  useEffect(() => watchSystemTheme(setSystemDark), []);
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const value = useMemo<ThemeState>(() => {
    const setPreference = (next: ThemePreference) => {
      writePreference(safeStorage(), next);
      setPreferenceState(next);
    };
    return {
      theme,
      preference,
      setPreference,
      toggle: () => {
        setPreference(theme === "dark" ? "light" : "dark");
      },
    };
  }, [theme, preference]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
