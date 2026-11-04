import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SESSION_KEY } from "./session";
import { fakeApi, json, problem } from "@/test/fakeApi";
import { mockSystemTheme } from "@/test/matchMedia";
import { renderApp, SESSION, signedInApi, STORE_ID } from "@/test/render";

const signedOut = () =>
  fakeApi()
    .on("GET /api/v1/auth/session", () => problem(401, "unauthenticated"))
    .on("GET /api/v1/ready", { status: "ready", database: "ok" })
    .on("GET /api/v1/auth/demo", { available: false, local_inbox: true });

/** A demo server: its demo store opens without an email (or fails as `opened` says). */
function demoServer(opened: () => Response = () => json(SESSION, 201), localInbox = true) {
  let session: unknown = null;
  return signedOut()
    .on("GET /api/v1/auth/demo", { available: true, local_inbox: localInbox })
    .on("GET /api/v1/auth/session", () =>
      session ? json(session) : problem(401, "unauthenticated"),
    )
    .on("POST /api/v1/auth/demo-session", () => {
      const answer = opened();
      if (answer.ok) session = SESSION;
      return answer;
    });
}

beforeEach(() => {
  mockSystemTheme(false);
  window.history.replaceState(null, "", "/");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function askForLink(email = "owner@example.com") {
  await userEvent.type(await screen.findByRole("textbox", { name: "Email" }), email);
  await userEvent.click(screen.getByRole("button", { name: "Email me a sign-in link" }));
}

describe("signing in by email link", () => {
  it("tells a demo server's visitor where its emails arrive", async () => {
    const fake = demoServer().on(
      "POST /api/v1/auth/magic-links",
      { status: "accepted", message: "ok" },
      202,
    );
    renderApp("/sign-in", fake.api);
    await askForLink();
    const inbox = await screen.findByRole("link", { name: "open it" });
    expect(inbox).toHaveAttribute("href", "http://localhost:8025");
  });

  it("sends a demo server's visitor to their own inbox when its emails are real", async () => {
    const fake = demoServer(undefined, false).on(
      "POST /api/v1/auth/magic-links",
      { status: "accepted", message: "ok" },
      202,
    );
    renderApp("/sign-in", fake.api);
    await askForLink();
    expect(await screen.findByRole("heading", { name: "Check your email" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "open it" })).not.toBeInTheDocument();
  });

  it("sends the owner to sign in, then back where they were", async () => {
    const fake = signedOut().on("POST /api/v1/auth/sessions", SESSION, 201);
    const { router } = renderApp("/goals", fake.api);
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/sign-in");
    });
    expect(
      await screen.findByRole("heading", { name: "Sign in to your store" }),
    ).toBeInTheDocument();
    expect(router.state.location.state).toEqual({ from: "/goals" });
  });

  it("asks for a link and says where it went, whether or not the address has an account", async () => {
    const fake = signedOut().on("POST /api/v1/auth/magic-links", { status: "accepted" }, 202);
    renderApp("/sign-in", fake.api);
    await askForLink("  alex@example.com ");
    expect(await screen.findByRole("heading", { name: "Check your email" })).toBeInTheDocument();
    expect(screen.getByText("alex@example.com")).toBeInTheDocument();
    const sent = fake.requests.find((request) => request.method === "POST");
    expect(await sent?.json()).toEqual({ email: "alex@example.com" });
    await userEvent.click(screen.getByRole("button", { name: "Use a different address" }));
    expect(screen.getByRole("textbox", { name: "Email" })).toHaveValue("");
  });

  it.each([
    [429, "Too many sign-in requests. Wait a minute, then try again."],
    [422, "Enter a valid email address."],
    [503, "The link could not be sent. Check your connection and try again."],
  ])("explains a refused request (%i)", async (status, message) => {
    const fake = signedOut().on("POST /api/v1/auth/magic-links", () => problem(status, "no"));
    renderApp("/sign-in", fake.api);
    await askForLink();
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.getByRole("textbox", { name: "Email" })).toHaveAttribute("aria-invalid", "true");
  });

  it("exchanges the link's token, out of the address bar first, and opens the store", async () => {
    window.history.replaceState(null, "", "/sign-in#token=Tok_123");
    let session: unknown = null;
    const fake = fakeApi()
      .on("GET /api/v1/auth/session", () =>
        session ? json(session) : problem(401, "unauthenticated"),
      )
      .on("GET /api/v1/ready", { status: "ready", database: "ok" })
      .on("POST /api/v1/auth/sessions", () => {
        session = SESSION;
        return json(SESSION, 201);
      });
    const { router, queries } = renderApp("/sign-in", fake.api);
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/");
    });
    expect(window.location.hash).toBe("");
    const exchange = fake.requests.find((request) => request.url.endsWith("/auth/sessions"));
    expect(await exchange?.json()).toEqual({ token: "Tok_123" });
    expect(queries.getQueryData(SESSION_KEY)).toEqual(SESSION);
  });

  it("exchanges a link opened in the same tab, where only the fragment changes", async () => {
    let session: unknown = null;
    const fake = signedOut()
      .on("GET /api/v1/auth/session", () =>
        session ? json(session) : problem(401, "unauthenticated"),
      )
      .on("POST /api/v1/auth/sessions", () => {
        session = SESSION;
        return json(SESSION, 201);
      });
    const { router } = renderApp("/sign-in", fake.api);
    await screen.findByRole("button", { name: "Email me a sign-in link" });
    window.history.replaceState(null, "", "/sign-in#token=Tok_456");
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/");
    });
    const exchange = fake.requests.find((request) => request.url.endsWith("/auth/sessions"));
    expect(await exchange?.json()).toEqual({ token: "Tok_456" });
  });

  it("says when a link has expired or was used, and offers a new one", async () => {
    window.history.replaceState(null, "", "/sign-in#token=old");
    const fake = signedOut().on("POST /api/v1/auth/sessions", () => problem(409, "used_link"));
    renderApp("/sign-in", fake.api);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This sign-in link has expired or was already used.",
    );
    expect(screen.getByRole("button", { name: "Email me a sign-in link" })).toBeInTheDocument();
  });

  it("tells a failed exchange from a refused link", async () => {
    window.history.replaceState(null, "", "/sign-in#token=tok");
    const fake = signedOut().on("POST /api/v1/auth/sessions", () => problem(503, "down"));
    renderApp("/sign-in", fake.api);
    expect(await screen.findByRole("alert")).toHaveTextContent("Signing in failed.");
  });

  it("skips the form when already signed in, never to another site", async () => {
    const { router } = renderApp("/sign-in", signedInApi().api);
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/");
    });
    await router.navigate("/sign-in", { state: { from: "//evil.example" } });
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/");
    });
  });
});

describe("exploring the demo store", () => {
  it("comes first on a demo server, and opens the store without an email", async () => {
    const fake = demoServer();
    const { router, queries } = renderApp("/sign-in", fake.api);
    const explore = await screen.findByRole("button", { name: "Explore the demo store" });
    expect(screen.getByRole("button", { name: "Email me a sign-in link" })).toBeVisible();
    await userEvent.click(explore);
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/");
    });
    expect(queries.getQueryData(SESSION_KEY)).toEqual(SESSION);
    expect(fake.requests.some((r) => r.url.includes("magic-links"))).toBe(false);
  });

  it("is not offered anywhere else", async () => {
    renderApp("/sign-in", signedOut().api);
    await screen.findByRole("button", { name: "Email me a sign-in link" });
    expect(screen.queryByRole("button", { name: "Explore the demo store" })).toBeNull();
  });

  it("says when the demo store cannot be opened", async () => {
    renderApp("/sign-in", demoServer(() => problem(503, "down")).api);
    await userEvent.click(await screen.findByRole("button", { name: "Explore the demo store" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be opened");
  });
});

describe("the gate of signed-in pages", () => {
  it("waits for the session, then opens the store", async () => {
    renderApp("/", signedInApi().api);
    expect(screen.getByText("Opening your store…")).toBeInTheDocument();
    expect(await screen.findByRole("navigation", { name: "Main" })).toBeInTheDocument();
  });

  it("offers to try again when the API cannot be reached", async () => {
    let up = false;
    const fake = signedInApi().on("GET /api/v1/auth/session", () =>
      up ? json(SESSION) : problem(503, "not_ready"),
    );
    renderApp("/", fake.api);
    const retry = await screen.findByRole("button", { name: "Try again" });
    up = true;
    await userEvent.click(retry);
    expect(await screen.findByRole("navigation", { name: "Main" })).toBeInTheDocument();
  });

  it("opens the store even when its name cannot be read", async () => {
    const fake = signedInApi().on(`GET /api/v1/stores/${STORE_ID}`, () => problem(503, "down"));
    renderApp("/", fake.api);
    expect(await screen.findByRole("banner")).toHaveTextContent("Your store");
  });

  it("says so when the account has no store", async () => {
    const fake = signedInApi().on("GET /api/v1/auth/session", { ...SESSION, store_ids: [] });
    renderApp("/", fake.api);
    expect(await screen.findByText("No store is linked to this account yet.")).toBeInTheDocument();
  });
});

describe("/demo", () => {
  it("opens a demo server's store on Home, without an email, in the light theme", async () => {
    window.localStorage.setItem("profit-agent.theme", "dark");
    const fake = demoServer();
    const { router, queries } = renderApp("/demo", fake.api);
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/");
    });
    expect(queries.getQueryData(SESSION_KEY)).toEqual(SESSION);
    expect(document.documentElement.dataset["theme"]).toBe("light");
    expect(window.localStorage.getItem("profit-agent.theme")).toBe("light");
    expect(fake.requests.some((r) => r.url.includes("magic-links"))).toBe(false);
  });

  it("says there is no demo store on any other server", async () => {
    renderApp("/demo", demoServer(() => problem(404, "not_found")).api);
    expect(await screen.findByText("This server has no demo store.")).toBeVisible();
    expect(screen.getByRole("link", { name: "Sign in to your store" })).toHaveAttribute(
      "href",
      "/sign-in",
    );
  });
});
