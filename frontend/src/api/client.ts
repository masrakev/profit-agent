/**
 * The typed API client: `paths` is generated from docs/api/openapi.json (`npm run api`), so a
 * call that does not match the contract does not compile, and a stale schema fails `npm run lint`.
 *
 * The platform and the API share one origin. The session cookie is HTTP-only; the CSRF cookie is
 * readable, and every state-changing request echoes it in `X-CSRF-Token` (double submit, ADR 0020).
 * Errors are RFC 9457 problem details, raised as `ApiError` by `unwrap`.
 */

import createClient, { type Middleware } from "openapi-fetch";

import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type Problem = Schemas["Problem"];

export const CSRF_COOKIE = "pa_csrf";
export const CSRF_HEADER = "X-CSRF-Token";
const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export function readCookie(name: string, cookies: string = document.cookie): string | undefined {
  for (const part of cookies.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return decodeURIComponent(rest.join("="));
  }
  return undefined;
}

const csrf: Middleware = {
  onRequest({ request }) {
    if (UNSAFE.has(request.method)) {
      const token = readCookie(CSRF_COOKIE);
      if (token) request.headers.set(CSRF_HEADER, token);
    }
    return request;
  },
};

export function createApi(fetchImpl?: typeof fetch) {
  const client = createClient<paths>({
    baseUrl: window.location.origin, // same origin: the platform and the API share one
    credentials: "same-origin",
    ...(fetchImpl ? { fetch: fetchImpl } : {}),
  });
  client.use(csrf);
  return client;
}

export type Api = ReturnType<typeof createApi>;

export const api: Api = createApi();

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: string | null;
  readonly requestId: string | null;
  readonly fields: readonly { field: string; message: string }[];

  constructor(status: number, problem: Partial<Problem> | undefined) {
    super(problem?.detail ?? problem?.title ?? `HTTP ${String(status)}`);
    this.name = "ApiError";
    this.status = status;
    this.code = problem?.code ?? "error";
    this.detail = problem?.detail ?? null;
    this.requestId = problem?.request_id ?? null;
    this.fields = problem?.errors ?? [];
  }

  /** The request will not succeed as it is: do not retry it. */
  get isClientError(): boolean {
    return this.status >= 400 && this.status < 500;
  }
}

interface Outcome<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

function isProblem(value: unknown): value is Partial<Problem> {
  return typeof value === "object" && value !== null;
}

/** The response's data, or an `ApiError` carrying the problem details. */
export async function unwrap<T>(pending: Promise<Outcome<T>>): Promise<T> {
  const { data, error, response } = await pending;
  if (error !== undefined || !response.ok) {
    throw new ApiError(response.status, isProblem(error) ? error : undefined);
  }
  return data as T;
}
