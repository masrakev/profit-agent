import { describe, expect, it } from "vitest";

import { DEMO_OWNER, demoSignIn } from "./demoSignIn";
import { fakeApi, json } from "@/test/fakeApi";

const SESSION = { kind: "session", actor: `owner:${DEMO_OWNER}`, store_ids: ["s1"] };

function mailpit(afterRequest: { id: string; text: string }[]) {
  let requested = false;
  const old = { ID: "old", To: [{ Address: DEMO_OWNER }] };
  const other = { ID: "other", To: [{ Address: "someone@example.com" }] };
  const fetchImpl = (url: string) => {
    if (url.includes("/messages?")) {
      const fresh = requested
        ? afterRequest.map((m) => ({ ID: m.id, To: [{ Address: DEMO_OWNER.toUpperCase() }] }))
        : [];
      return Promise.resolve(json({ messages: [...fresh, old, other] }));
    }
    const id = url.split("/").pop();
    return Promise.resolve(json({ Text: afterRequest.find((m) => m.id === id)?.text ?? "" }));
  };
  return {
    fetchImpl: fetchImpl as unknown as typeof fetch,
    markRequested: () => {
      requested = true;
    },
  };
}

describe("the demo sign-in (development only)", () => {
  it("signs in with the link from the email the API just sent", async () => {
    const inbox = mailpit([
      {
        id: "new",
        text: "Sign in with this link:\n\nhttp://localhost:3000/sign-in#token=Demo_Token-1\n",
      },
    ]);
    const fake = fakeApi()
      .on("POST /api/v1/auth/magic-links", () => {
        inbox.markRequested();
        return json({ status: "accepted" }, 202);
      })
      .on("POST /api/v1/auth/sessions", SESSION, 201);
    const session = await demoSignIn(fake.api, {
      fetchImpl: inbox.fetchImpl,
      sleep: () => Promise.resolve(),
    });
    expect(session).toEqual(SESSION);
    expect(await fake.requests[0]?.json()).toEqual({ email: DEMO_OWNER });
    expect(await fake.requests[1]?.json()).toEqual({ token: "Demo_Token-1" });
  });

  it("never reuses an older email, and gives up after a while", async () => {
    const inbox = mailpit([{ id: "new", text: "no link in this one" }]);
    const fake = fakeApi().on("POST /api/v1/auth/magic-links", () => {
      inbox.markRequested();
      return json({ status: "accepted" }, 202);
    });
    await expect(
      demoSignIn(fake.api, {
        fetchImpl: inbox.fetchImpl,
        attempts: 3,
        sleep: () => Promise.resolve(),
      }),
    ).rejects.toThrow("no sign-in email reached Mailpit");
    expect(fake.requests).toHaveLength(1); // no session was asked for
  });

  it("says when Mailpit is down", async () => {
    const down = (() =>
      Promise.resolve(new Response(null, { status: 502 }))) as unknown as typeof fetch;
    await expect(demoSignIn(fakeApi().api, { fetchImpl: down })).rejects.toThrow("make up");
  });
});
