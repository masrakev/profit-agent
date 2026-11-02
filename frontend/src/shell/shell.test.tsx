import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Composer, COMPOSER_PROMISE } from "./Composer";
import { problem } from "@/test/fakeApi";
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
    const links = within(rail).getAllByRole("link");
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
    await userEvent.click(screen.getByRole("link", { name: "Goals" }));
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

  it("keeps the question while it cannot send, and asks by voice when it can", async () => {
    const onVoice = vi.fn();
    const { rerender } = render(<Composer />);
    expect(screen.getByRole("button", { name: "Ask by voice" })).toBeDisabled();
    await userEvent.type(screen.getByRole("textbox"), "Hello{Enter}");
    expect(screen.getByRole("textbox")).toHaveValue("Hello");
    rerender(<Composer onVoice={onVoice} />);
    await userEvent.click(screen.getByRole("button", { name: "Ask by voice" }));
    expect(onVoice).toHaveBeenCalledOnce();
  });
});
