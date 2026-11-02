import { describe, expect, it } from "vitest";

import { readEvents, type ServerEvent } from "./sse";

function stream(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

async function all(body: ReadableStream<Uint8Array>): Promise<ServerEvent[]> {
  const out: ServerEvent[] = [];
  for await (const event of readEvents(body)) out.push(event);
  return out;
}

describe("server-sent events", () => {
  it("are read as they arrive, whatever the chunks", async () => {
    const events = await all(
      stream(
        'id: 1\nevent: step\ndata: {"kind":"st',
        'arted"}\n\n: keep-alive\n\nevent: answer\r\nid: 2\r\ndata: {"status":"answered"}\r\n\r\n',
        "event: done\ndata: {}",
      ),
    );
    expect(events).toEqual([
      { event: "step", data: { kind: "started" }, id: "1" },
      { event: "answer", data: { status: "answered" }, id: "2" },
      { event: "done", data: {}, id: null },
    ]);
  });

  it("keep text that is not JSON, join data lines, and skip empty events", async () => {
    const events = await all(stream("data: one\ndata: two\n\nevent: ping\n\nretry\ndata:x\n\n"));
    expect(events).toEqual([
      { event: "message", data: "one\ntwo", id: null },
      { event: "message", data: "x", id: null },
    ]);
  });
});
