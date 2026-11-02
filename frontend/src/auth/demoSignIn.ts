/**
 * Development only: sign in as the demo store's owner (`make demo-seed`) in one click.
 *
 * It asks the API for a sign-in link like anyone would, then reads that email from Mailpit (the
 * local SMTP inbox of docker compose, reached through the dev server's `/__mailpit` proxy) and
 * exchanges its token. Nothing here exists in a production build: the only import of this module
 * sits behind `import.meta.env.DEV`, which the build replaces by `false` and drops.
 */

import { unwrap, type Api } from "@/api/client";

import { openSession, tokenFromFragment, type Session } from "./session";

export const DEMO_OWNER = "owner@example.com";
const MAILPIT = "/__mailpit/api/v1";
const LINK = /\/sign-in#(token=[A-Za-z0-9_-]+)/;

interface MailpitMessage {
  ID: string;
  To: { Address: string }[];
}

interface Options {
  fetchImpl?: typeof fetch;
  attempts?: number;
  delayMs?: number;
  sleep?: (ms: number) => Promise<void>;
}

const wait = (ms: number) =>
  new Promise<void>((resolve) => {
    setTimeout(resolve, ms);
  });

async function messageIds(fetchImpl: typeof fetch): Promise<Set<string>> {
  const response = await fetchImpl(`${MAILPIT}/messages?limit=50`);
  if (!response.ok) throw new Error("Mailpit is not reachable: run `make up`");
  const body = (await response.json()) as { messages?: MailpitMessage[] };
  return new Set(
    (body.messages ?? [])
      .filter((m) => m.To.some((to) => to.Address.toLowerCase() === DEMO_OWNER))
      .map((m) => m.ID),
  );
}

export async function demoSignIn(api: Api, options: Options = {}): Promise<Session> {
  const { fetchImpl = fetch, attempts = 20, delayMs = 250, sleep = wait } = options;
  const before = await messageIds(fetchImpl);
  await unwrap(api.POST("/api/v1/auth/magic-links", { body: { email: DEMO_OWNER } }));
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const fresh = [...(await messageIds(fetchImpl))].filter((id) => !before.has(id));
    for (const id of fresh) {
      const message = (await (await fetchImpl(`${MAILPIT}/message/${id}`)).json()) as {
        Text?: string;
      };
      const found = LINK.exec(message.Text ?? "");
      const token = found?.[1] ? tokenFromFragment(found[1]) : null;
      if (token) return openSession(api, token);
    }
    await sleep(delayMs);
  }
  throw new Error("no sign-in email reached Mailpit: is the demo store seeded (`make demo-seed`)?");
}
