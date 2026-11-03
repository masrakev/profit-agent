import { describe, expect, it, vi } from "vitest";

import {
  THEME_STORAGE_KEY,
  applyTheme,
  initTheme,
  readPreference,
  resolveTheme,
  watchSystemTheme,
  writePreference,
} from "./theme";
import { mockSystemTheme } from "@/test/matchMedia";

describe("resolveTheme", () => {
  it("follows the system unless the owner picked a theme", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });
});

describe("the remembered pick", () => {
  it("starts light, then reads and writes the pick, the system theme included", () => {
    const storage = new Map<string, string>();
    const fake = {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
    };
    expect(readPreference(fake)).toBe("light"); // light by default
    writePreference(fake, "dark");
    expect(storage.get(THEME_STORAGE_KEY)).toBe("dark");
    expect(readPreference(fake)).toBe("dark");
    writePreference(fake, "system");
    expect(readPreference(fake)).toBe("system");
    storage.set(THEME_STORAGE_KEY, "sepia");
    expect(readPreference(fake)).toBe("light"); // unknown values are ignored
  });

  it("survives a storage that refuses", () => {
    const refusing = {
      getItem: () => {
        throw new Error("denied");
      },
      setItem: () => {
        throw new Error("denied");
      },
      removeItem: () => {
        throw new Error("denied");
      },
    };
    expect(readPreference(refusing)).toBe("light");
    expect(() => {
      writePreference(refusing, "dark");
    }).not.toThrow();
    expect(readPreference(null)).toBe("light");
  });
});

describe("applying the theme", () => {
  it("sets data-theme and color-scheme on the root", () => {
    const root = document.createElement("html");
    applyTheme("dark", root);
    expect(root.dataset["theme"]).toBe("dark");
    expect(root.style.colorScheme).toBe("dark");
  });

  it("applies light before the first render, even when the system is dark", () => {
    mockSystemTheme(true);
    expect(initTheme()).toBe("light");
    expect(document.documentElement.dataset["theme"]).toBe("light");
  });

  it("watches the system theme until unsubscribed", () => {
    const system = mockSystemTheme(false);
    const onChange = vi.fn();
    const stop = watchSystemTheme(onChange);
    system.change(true);
    stop();
    system.change(false);
    expect(onChange.mock.calls).toEqual([[true]]);
  });
});
