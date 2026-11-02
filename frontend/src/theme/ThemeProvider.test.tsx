import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useTheme } from "./context";
import { THEME_STORAGE_KEY } from "./theme";
import { ThemeProvider } from "./ThemeProvider";
import { mockSystemTheme } from "@/test/matchMedia";

function Probe() {
  const { theme, preference, toggle } = useTheme();
  return (
    <button type="button" onClick={toggle}>
      {theme} / {preference}
    </button>
  );
}

afterEach(() => {
  window.localStorage.clear();
  vi.unstubAllGlobals();
});

describe("ThemeProvider", () => {
  it("follows the system theme while nothing is picked", () => {
    const system = mockSystemTheme(false);
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    expect(screen.getByRole("button")).toHaveTextContent("light / system");
    act(() => {
      system.change(true);
    });
    expect(screen.getByRole("button")).toHaveTextContent("dark / system");
    expect(document.documentElement.dataset["theme"]).toBe("dark");
  });

  it("remembers the owner's pick over the system theme", async () => {
    const system = mockSystemTheme(false);
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    await userEvent.click(screen.getByRole("button"));
    expect(screen.getByRole("button")).toHaveTextContent("dark / dark");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    act(() => {
      system.change(false);
    });
    expect(document.documentElement.dataset["theme"]).toBe("dark");
  });

  it("needs a provider", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(() => render(<Probe />)).toThrow("useTheme needs a ThemeProvider");
  });
});
