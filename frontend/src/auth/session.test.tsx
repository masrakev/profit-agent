import { act, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  SESSION_KEY,
  clearFragment,
  fetchSession,
  tokenFromFragment,
  useOpenSession,
  useRequestLink,
  useSession,
  useSignOut,
} from "./session";
import { fakeApi, json, problem } from "@/test/fakeApi";
import { renderHookWithApi } from "@/test/render";

const SESSION = {
  kind: "session",
  actor: "owner:owner@example.com",
  store_ids: ["ed68bb6d-1d14-5b04-af2b-e272de12e862"],
  csrf_token: null,
  expires_at: "2026-12-02T00:00:00Z",
};

describe("the session", () => {
  it("is null when nobody is signed in", async () => {
    const fake = fakeApi().on("GET /api/v1/auth/session", () => problem(401, "unauthenticated"));
    await expect(fetchSession(fake.api)).resolves.toBeNull();
  });

  it("is the API's session, and other failures stay errors", async () => {
    const fake = fakeApi().on("GET /api/v1/auth/session", SESSION);
    await expect(fetchSession(fake.api)).resolves.toEqual(SESSION);
    fake.on("GET /api/v1/auth/session", () => problem(503, "not_ready"));
    await expect(fetchSession(fake.api)).rejects.toMatchObject({ status: 503 });
  });

  it("is read by useSession", async () => {
    const fake = fakeApi().on("GET /api/v1/auth/session", SESSION);
    const { result } = renderHookWithApi(() => useSession(), fake.api);
    await waitFor(() => {
      expect(result.current.data).toEqual(SESSION);
    });
  });
});

describe("signing in and out", () => {
  it("asks for a link with the address", async () => {
    const fake = fakeApi().on("POST /api/v1/auth/magic-links", { status: "accepted" }, 202);
    const { result } = renderHookWithApi(() => useRequestLink(), fake.api);
    await act(() => result.current.mutateAsync("owner@example.com"));
    expect(await fake.requests[0]?.json()).toEqual({ email: "owner@example.com" });
  });

  it("opens a session from the token and remembers it", async () => {
    const fake = fakeApi().on("POST /api/v1/auth/sessions", SESSION, 201);
    const { result, queries } = renderHookWithApi(() => useOpenSession(), fake.api);
    await act(() => result.current.mutateAsync("tok_123"));
    expect(await fake.requests[0]?.json()).toEqual({ token: "tok_123" });
    expect(queries.getQueryData(SESSION_KEY)).toEqual(SESSION);
  });

  it("forgets everything on sign out", async () => {
    const fake = fakeApi().on(
      "DELETE /api/v1/auth/session",
      () => new Response(null, { status: 204 }),
    );
    const { result, queries } = renderHookWithApi(() => useSignOut(), fake.api);
    queries.setQueryData(["overview"], { headline: "x" });
    await act(() => result.current.mutateAsync());
    expect(queries.getQueryData(["overview"])).toBeUndefined();
    expect(queries.getQueryData(SESSION_KEY)).toBeNull();
  });

  it("reports a used link as the API says", async () => {
    const fake = fakeApi().on("POST /api/v1/auth/sessions", () => problem(409, "used_link"));
    const { result } = renderHookWithApi(() => useOpenSession(), fake.api);
    await expect(act(() => result.current.mutateAsync("tok"))).rejects.toMatchObject({
      code: "used_link",
    });
    expect(json(undefined).status).toBe(200);
  });
});

describe("the link's token", () => {
  it("is read from the fragment, and only if well formed", () => {
    expect(tokenFromFragment("#token=AbC-_09")).toBe("AbC-_09");
    expect(tokenFromFragment("token=xyz")).toBe("xyz");
    expect(tokenFromFragment("#token=<script>")).toBeNull();
    expect(tokenFromFragment("#other=1")).toBeNull();
    expect(tokenFromFragment("")).toBeNull();
  });

  it("is removed from the address bar", () => {
    window.history.pushState({}, "", "/sign-in?next=%2F#token=secret");
    clearFragment();
    expect(window.location.hash).toBe("");
    expect(window.location.pathname + window.location.search).toBe("/sign-in?next=%2F");
  });
});
