import { renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import { createQueryClient } from "@/api/queryClient";
import { routes } from "@/router";
import { initials, storeLabel, storeLine, useStore } from "@/stores/store";
import { estimate, exact } from "@/test/facts";
import { mockSystemTheme } from "@/test/matchMedia";
import { renderApp, signedInApi, STORE_ID } from "@/test/render";

beforeEach(() => {
  mockSystemTheme(false);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const paths = (dev: boolean) =>
  JSON.stringify(routes(dev), (key, value: unknown) => (key === "element" ? undefined : value));

describe("the routes", () => {
  it("serve the component catalogue in development builds only", () => {
    expect(paths(true)).toContain('"style-guide"');
    expect(paths(false)).not.toContain("style-guide");
  });

  it("answer an unknown address with a way back", async () => {
    renderApp("/nowhere", signedInApi().api);
    expect(await screen.findByRole("heading", { name: "Nothing here" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to your store" })).toHaveAttribute("href", "/");
  });
});

describe("an expired session", () => {
  it("is reported once a request is refused for it, and only then", async () => {
    const onUnauthenticated = vi.fn();
    const client = createQueryClient({ onUnauthenticated });
    await client
      .query({ queryKey: ["a"], queryFn: () => Promise.reject(new ApiError(403, undefined)) })
      .catch(() => undefined);
    expect(onUnauthenticated).not.toHaveBeenCalled();
    await client
      .query({ queryKey: ["b"], queryFn: () => Promise.reject(new ApiError(401, undefined)) })
      .catch(() => undefined);
    expect(onUnauthenticated).toHaveBeenCalledWith(client);
    await expect(
      client
        .getMutationCache()
        .build(client, {
          mutationFn: () => Promise.reject(new ApiError(401, undefined)),
        })
        .execute(undefined),
    ).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthenticated).toHaveBeenCalledTimes(2);
    createQueryClient(); // no callback: a refused request is only an error
  });
});

describe("the store", () => {
  it("is named, or called your store until the API names it", () => {
    expect(storeLabel({ name: "Northwind Outdoor" })).toBe("Northwind Outdoor");
    expect(storeLabel({ name: null })).toBe("Your store");
    expect(storeLine({ storeId: STORE_ID, name: "Acme", synthetic: false })).toBe("Acme");
    expect(storeLine({ storeId: STORE_ID, name: "Acme", synthetic: true })).toBe(
      "Acme · Demo store",
    );
    expect(initials("Northwind Outdoor")).toBe("NO");
    expect(initials("  acme  ")).toBe("A");
  });

  it("needs a signed-in session above it", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(() => renderHook(() => useStore())).toThrow("signed-in session");
  });
});

describe("the component catalogue (development builds)", () => {
  const decision = {
    decision_id: "d1",
    status: "proposed",
    cause: "stockout_on_promoted",
    horizon_days: 14,
    recommended_option_id: "pause",
    options: [
      {
        option_id: "pause",
        kind: "pause_until_restock",
        impact_fact_id: 13,
        reversibility: "reversible",
      },
      { option_id: "cut", kind: "reduce_budget", impact_fact_id: 14, reversibility: "reversible" },
    ],
  };
  const cut = { ...estimate, fact_id: 14, formatted: "$150.00–$205.00" };

  it("lays out the style guide with the store's own numbers", async () => {
    const facts = `/api/v1/stores/${STORE_ID}/facts`;
    const fake = signedInApi()
      .on(`GET /api/v1/stores/${STORE_ID}/overview`, {
        facts: { "12": exact, "13": estimate },
        names: {},
        headline: "",
        sections: [],
      })
      .on(`GET /api/v1/stores/${STORE_ID}/decisions`, { items: [decision], next_cursor: null })
      .on(`GET ${facts}/13`, { fact: estimate, formula: null, parents: [], sources: [] })
      .on(`GET ${facts}/14`, { fact: cut, formula: null, parents: [], sources: [] });
    renderApp("/style-guide", fake.api, { dev: true });
    expect(
      await screen.findByRole("heading", { name: "A calm workspace for clearer decisions." }),
    ).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Dark · Quiet contrast" })).toHaveAttribute(
      "data-theme",
      "dark",
    );
    expect(
      await screen.findByRole("article", { name: "Pause until restock?" }),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(
        screen.getAllByRole("button", { name: "$150.00–$205.00, see the proof" }).length,
      ).toBeGreaterThan(0);
    });
    expect(screen.getByRole("button", { name: "$1,234.50, see the proof" })).toBeInTheDocument();
  });

  it("says when the store has nothing to show", async () => {
    const fake = signedInApi()
      .on(`GET /api/v1/stores/${STORE_ID}/overview`, {
        facts: {},
        names: {},
        headline: "",
        sections: [],
      })
      .on(`GET /api/v1/stores/${STORE_ID}/decisions`, { items: [], next_cursor: null });
    renderApp("/style-guide", fake.api, { dev: true });
    expect(await screen.findAllByText(/run make demo-seed/)).toHaveLength(2);
  });
});
