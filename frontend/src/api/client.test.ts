import { describe, expect, it, vi } from "vitest";

import { ApiError, CSRF_HEADER, createApi, readCookie, unwrap } from "./client";
import { shouldRetry } from "./queryClient";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": status < 400 ? "application/json" : "application/problem+json" },
  });
}

describe("readCookie", () => {
  it("finds a cookie among others and decodes it", () => {
    expect(readCookie("pa_csrf", "a=1; pa_csrf=x%2By; b=2")).toBe("x+y");
    expect(readCookie("pa_csrf", "a=1")).toBeUndefined();
    expect(readCookie("pa_csrf", "pa_csrf=a=b")).toBe("a=b");
  });
});

describe("the API client", () => {
  it("echoes the CSRF cookie on state-changing requests only", async () => {
    document.cookie = "pa_csrf=token-123; path=/";
    const seen: Request[] = [];
    const fetchImpl = vi.fn((input: Request) => {
      seen.push(input);
      return Promise.resolve(json({ kind: "session", actor: "owner", store_ids: [] }));
    });
    const api = createApi(fetchImpl as unknown as typeof fetch);
    await api.GET("/api/v1/auth/session");
    await api.POST("/api/v1/auth/sessions", { body: { token: "t" } });
    expect(seen[0]?.headers.get(CSRF_HEADER)).toBeNull();
    expect(seen[1]?.headers.get(CSRF_HEADER)).toBe("token-123");
    expect(seen[1]?.credentials).toBe("same-origin");
  });

  it("sends no CSRF header when there is no session", async () => {
    const seen: Request[] = [];
    const api = createApi(((input: Request) => {
      seen.push(input);
      return Promise.resolve(json({}));
    }) as unknown as typeof fetch);
    await api.POST("/api/v1/auth/magic-links", { body: { email: "owner@example.com" } });
    expect(seen[0]?.headers.has(CSRF_HEADER)).toBe(false);
  });
});

describe("unwrap", () => {
  it("returns the data of a successful response", async () => {
    const api = createApi(() => Promise.resolve(json({ status: "ok" })));
    await expect(unwrap(api.GET("/api/v1/health"))).resolves.toEqual({ status: "ok" });
  });

  it("raises the problem details as an ApiError", async () => {
    const problem = {
      type: "urn:profit-agent:problem:not_found",
      title: "Not Found",
      status: 404,
      detail: "no such store",
      code: "not_found",
      request_id: "req-1",
    };
    const api = createApi(() => Promise.resolve(json(problem, 404)));
    const error = await unwrap(api.GET("/api/v1/health")).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 404,
      code: "not_found",
      detail: "no such store",
      requestId: "req-1",
      message: "no such store",
      isClientError: true,
    });
  });

  it("raises an ApiError without a body", async () => {
    const api = createApi(() => Promise.resolve(new Response(null, { status: 502 })));
    const error = await unwrap(api.GET("/api/v1/health")).catch((e: unknown) => e);
    expect(error).toMatchObject({ status: 502, code: "error", isClientError: false });
  });
});

describe("shouldRetry", () => {
  it("retries transient failures twice, never a refusal", () => {
    expect(shouldRetry(0, new ApiError(503, undefined))).toBe(true);
    expect(shouldRetry(2, new ApiError(503, undefined))).toBe(false);
    expect(shouldRetry(0, new ApiError(404, undefined))).toBe(false);
    expect(shouldRetry(0, new TypeError("network"))).toBe(true);
  });
});
