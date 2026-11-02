/**
 * Server-sent events from a response body. EventSource only GETs; Ask posts its question, so the
 * stream is read here: events are separated by a blank line, `event:` names one, `data:` lines
 * carry its JSON, `id:` its sequence, and comment lines (`: keep-alive`) are skipped.
 */

export interface ServerEvent {
  event: string;
  data: unknown;
  id: string | null;
}

function parse(block: string): ServerEvent | null {
  let event = "message";
  let id: string | null = null;
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
    else if (field === "id") id = value;
  }
  if (data.length === 0) return null;
  const text = data.join("\n");
  try {
    return { event, data: JSON.parse(text) as unknown, id };
  } catch {
    return { event, data: text, id };
  }
}

/** Every event of `body`, in order, until the stream ends. */
export async function* readEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<ServerEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n?/g, "\n");
      let end = buffer.indexOf("\n\n");
      while (end !== -1) {
        const event = parse(buffer.slice(0, end));
        buffer = buffer.slice(end + 2);
        if (event) yield event;
        end = buffer.indexOf("\n\n");
      }
    }
    const last = parse(buffer);
    if (last) yield last;
  } finally {
    reader.releaseLock();
  }
}
