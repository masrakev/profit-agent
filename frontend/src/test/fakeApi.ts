import { createApi, type Api } from "@/api/client";

type Handler = (request: Request) => Response | Promise<Response>;

export interface FakeApi {
  api: Api;
  /** Every request received, in order. */
  requests: Request[];
  /** Answers `METHOD /path` (exact path, query ignored). */
  /** A handler, or a JSON body answered with `status`. */
  on: (route: string, handler: unknown, status?: number) => FakeApi;
}

export function json(body: unknown, status = 200): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": status < 400 ? "application/json" : "application/problem+json" },
  });
}

export function problem(status: number, code: string, detail = code): Response {
  return json(
    { type: `urn:profit-agent:problem:${code}`, title: code, status, code, detail },
    status,
  );
}

/** An API client whose `fetch` answers from routes; an unknown route is a 404 problem. */
export function fakeApi(): FakeApi {
  const routes = new Map<string, Handler>();
  const requests: Request[] = [];
  const fetchImpl = async (input: Request) => {
    requests.push(input.clone());
    const route = `${input.method} ${new URL(input.url).pathname}`;
    const handler = routes.get(route);
    return handler ? handler(input) : problem(404, "not_found", `no route ${route}`);
  };
  const fake: FakeApi = {
    api: createApi(fetchImpl as unknown as typeof fetch),
    requests,
    on(route, handler, status = 200) {
      routes.set(
        route,
        typeof handler === "function" ? (handler as Handler) : () => json(handler, status),
      );
      return fake;
    },
  };
  return fake;
}
