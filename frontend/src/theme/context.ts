import { createContext, useContext } from "react";

import type { Theme, ThemePreference } from "./theme";

export interface ThemeState {
  theme: Theme;
  preference: ThemePreference;
  setPreference: (preference: ThemePreference) => void;
  /** Switches to the other theme, as an explicit pick. */
  toggle: () => void;
}

export const ThemeContext = createContext<ThemeState | null>(null);

export function useTheme(): ThemeState {
  const state = useContext(ThemeContext);
  if (!state) throw new Error("useTheme needs a ThemeProvider above it");
  return state;
}
