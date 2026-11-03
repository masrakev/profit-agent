import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Composer, COMPOSER_PROMISE } from "./Composer";
import { readCollapsed, SIDEBAR_STORAGE_KEY, writeCollapsed } from "./sidebar";
import { problem } from "@/test/fakeApi";
import { MAX_SECONDS, type Recorder } from "@/voice/recorder";
import { mockSystemTheme } from "@/test/matchMedia";
import { renderApp, signedInApi } from "@/test/render";

beforeEach(() => {
  mockSystemTheme(false);
});

afterEach(() => {
  window.localStorage.clear();
  vi.unstubAllGlobals();
});

describe("the app shell", () => {
  it("has the rail's six destinations, the current one marked", async () => {
    renderApp("/", signedInApi().api);
    const rail = await screen.findByRole("navigation", { name: "Main" });
    const links = within(within(rail).getByRole("list")).getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual([
      "Chat",
      "Today",
      "Decisions",
      "Goals",
      "Journal",
      "Settings",
    ]);
    expect(within(rail).getByRole("link", { name: "Chat" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await userEvent.click(within(rail).getByRole("link", { name: "Today" }));
    expect(screen.getByRole("heading", { name: "Today" })).toBeInTheDocument();
    expect(within(rail).getByRole("link", { name: "Chat" })).not.toHaveAttribute("aria-current");
  });

  it("docks the composer in the conversation only", async () => {
    renderApp("/", signedInApi().api);
    expect(
      await screen.findByRole("textbox", { name: "Ask anything about your store" }),
    ).toBeVisible();
    expect(screen.getByText(COMPOSER_PROMISE)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "Journal" }));
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("shows the store and the brand in the header, and a skip link", async () => {
    renderApp("/", signedInApi().api);
    const header = await screen.findByRole("banner");
    expect(within(header).getByText("Northwind Outdoor · Demo store")).toBeInTheDocument();
    expect(within(header).getByText("Profit Agent")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main");
  });

  it("switches the theme from the rail", async () => {
    renderApp("/", signedInApi().api);
    await userEvent.click(await screen.findByRole("button", { name: "Use the dark theme" }));
    expect(document.documentElement.dataset["theme"]).toBe("dark");
    await userEvent.click(screen.getByRole("button", { name: "Use the light theme" }));
    expect(document.documentElement.dataset["theme"]).toBe("light");
  });

  it("says whether the platform answers", async () => {
    renderApp("/", signedInApi().api);
    expect(await screen.findByText("Connected")).toBeInTheDocument();
  });

  it("says so when it does not", async () => {
    const fake = signedInApi().on("GET /api/v1/ready", () => problem(503, "not_ready"));
    renderApp("/", fake.api);
    expect(await screen.findByText("Not connected")).toBeInTheDocument();
  });

  it("names the store in its menu and signs out from it", async () => {
    const fake = signedInApi().on(
      "DELETE /api/v1/auth/session",
      () => new Response(null, { status: 204 }),
    );
    const { router } = renderApp("/", fake.api);
    const store = await screen.findByRole("button", { name: /Northwind Outdoor/ });
    expect(store).toHaveTextContent("NO");
    await userEvent.click(store);
    const menu = screen.getByRole("menu", { name: "Northwind Outdoor" });
    const signOut = within(menu).getByRole("menuitem", { name: "Sign out" });
    expect(signOut).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(menu).not.toBeVisible();
    expect(store).toHaveFocus();
    await userEvent.click(store);
    await userEvent.click(document.body);
    expect(menu).not.toBeVisible();
    await userEvent.click(store);
    await userEvent.keyboard("a");
    await userEvent.click(signOut);
    await waitFor(
      () => {
        expect(router.state.location.pathname).toBe("/sign-in");
      },
      { timeout: 3000 }, // the sign-out request, then the navigation: slow under load
    );
    expect(fake.requests.some((request) => request.method === "DELETE")).toBe(true);
  });
});

describe("the sidebar", () => {
  it("is expanded by default: each destination is an icon and its label", async () => {
    renderApp("/", signedInApi().api);
    const rail = await screen.findByRole("navigation", { name: "Main" });
    expect(rail).toHaveAttribute("data-collapsed", "false");
    expect(within(rail).getByText("Decisions")).not.toHaveClass("sr-only");
    expect(within(rail).getByText("Dark theme")).toBeVisible();
    expect(rail.querySelector("[aria-hidden=true].pointer-events-none")).toBeNull(); // no tips
  });

  it("collapses to icons, which name themselves on hover, and expands again", async () => {
    renderApp("/", signedInApi().api);
    await userEvent.click(await screen.findByRole("button", { name: "Close sidebar" }));
    const rail = screen.getByRole("navigation", { name: "Main" });
    expect(rail).toHaveAttribute("data-collapsed", "true");
    const decisions = within(rail).getByRole("link", { name: "Decisions" }); // still named
    expect(within(decisions).getByText("Decisions")).toHaveClass("sr-only");
    expect(within(rail).getAllByText("Decisions")).toHaveLength(2); // its label, and its tip
    expect(window.localStorage.getItem(SIDEBAR_STORAGE_KEY)).toBe("collapsed");
    await userEvent.click(within(rail).getByRole("button", { name: "Open sidebar" }));
    expect(rail).toHaveAttribute("data-collapsed", "false");
    expect(window.localStorage.getItem(SIDEBAR_STORAGE_KEY)).toBe("expanded");
  });

  it("remembers the owner's choice", async () => {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, "collapsed");
    renderApp("/", signedInApi().api);
    expect(await screen.findByRole("button", { name: "Open sidebar" })).toBeInTheDocument();
  });

  it("still works when storage is refused", () => {
    const refusing = {
      getItem: () => {
        throw new Error("denied");
      },
      setItem: () => {
        throw new Error("denied");
      },
    };
    expect(readCollapsed(refusing)).toBe(false);
    expect(readCollapsed(null)).toBe(false);
    expect(() => {
      writeCollapsed(refusing, true);
    }).not.toThrow();
  });
});

describe("the composer", () => {
  it("sends the trimmed question and clears itself", async () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} />);
    const box = screen.getByRole("textbox", { name: "Ask anything about your store" });
    await userEvent.type(box, "   {Enter}");
    expect(onSend).not.toHaveBeenCalled();
    await userEvent.type(box, "  Why did profit drop?  {Enter}");
    expect(onSend).toHaveBeenCalledWith("Why did profit drop?");
    expect(box).toHaveValue("");
  });

  it("keeps the question while it cannot send", async () => {
    render(<Composer />);
    expect(screen.getByRole("button", { name: "Ask by voice" })).toBeDisabled();
    await userEvent.type(screen.getByRole("textbox"), "Hello{Enter}");
    expect(screen.getByRole("textbox")).toHaveValue("Hello");
  });

  function fakeRecorder(overrides: Partial<Recorder> = {}) {
    const recorder: Recorder = {
      start: vi.fn(() => Promise.resolve()),
      stop: vi.fn(() => Promise.resolve(new Blob(["sound"], { type: "audio/webm" }))),
      cancel: vi.fn(),
      samples: () => new Uint8Array([128, 255, 0, 140]),
      ...overrides,
    };
    return { recorder, factory: () => recorder };
  }

  it("records a spoken question with its waveform, then sends it", async () => {
    const paint = { clearRect: vi.fn(), fillRect: vi.fn(), fillStyle: "" };
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
      paint as unknown as CanvasRenderingContext2D,
    );
    const onVoice = vi.fn();
    const { recorder, factory } = fakeRecorder();
    render(<Composer onVoice={onVoice} recorder={factory} />);
    await userEvent.click(screen.getByRole("button", { name: "Ask by voice" }));
    const group = screen.getByRole("group", { name: "Recording your question" });
    expect(within(group).getByRole("status")).toHaveTextContent("Listening");
    await waitFor(() => {
      expect(paint.fillRect).toHaveBeenCalled();
    });
    await userEvent.click(within(group).getByRole("button", { name: "Send" }));
    expect(recorder.stop).toHaveBeenCalledOnce();
    expect(onVoice).toHaveBeenCalledWith(expect.any(Blob));
    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });

  it("drops a cancelled or empty recording", async () => {
    const onVoice = vi.fn();
    const { recorder, factory } = fakeRecorder({
      stop: vi.fn(() => Promise.resolve(new Blob([]))),
    });
    render(<Composer onVoice={onVoice} recorder={factory} />);
    await userEvent.click(screen.getByRole("button", { name: "Ask by voice" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel the recording" }));
    expect(recorder.cancel).toHaveBeenCalledOnce();
    await userEvent.click(screen.getByRole("button", { name: "Ask by voice" }));
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(onVoice).not.toHaveBeenCalled();
  });

  it("says when the microphone is not available", async () => {
    const { factory } = fakeRecorder({ start: () => Promise.reject(new Error("denied")) });
    render(<Composer onVoice={vi.fn()} recorder={factory} />);
    await userEvent.click(screen.getByRole("button", { name: "Ask by voice" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The microphone is not available");
    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });

  it("stops by itself at two minutes, and when it leaves the page", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"], shouldAdvanceTime: true });
    try {
      const onVoice = vi.fn();
      const { recorder, factory } = fakeRecorder();
      const { unmount } = render(<Composer onVoice={onVoice} recorder={factory} />);
      fireEvent.click(screen.getByRole("button", { name: "Ask by voice" }));
      await screen.findByRole("group", { name: "Recording your question" });
      await act(() => vi.advanceTimersByTimeAsync(MAX_SECONDS * 1000));
      expect(onVoice).toHaveBeenCalledOnce();
      fireEvent.click(screen.getByRole("button", { name: "Ask by voice" }));
      await screen.findByRole("group", { name: "Recording your question" });
      unmount();
      expect(recorder.cancel).toHaveBeenCalledOnce();
    } finally {
      vi.useRealTimers();
    }
  });
});
