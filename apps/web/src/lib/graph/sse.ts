export type SSEEvent = { event: string; data: unknown };

/**
 * Parses a fetch Response's body (services/api's chat stream, proxied
 * through /api/chat/sessions/{id}/stream) into individual SSE events as
 * they arrive — not after the whole response finishes, which is the
 * whole point: Stage 2.4's graph pulse needs to react to the
 * `retrieval` event the moment it lands, before any `token` event.
 */
export async function* parseSSEStream(
  body: ReadableStream<Uint8Array>
): AsyncGenerator<SSEEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // Events are separated by a blank line ("\n\n"), per the SSE
      // format services/api's chat/stream.py emits.
      let separatorIndex: number;
      while ((separatorIndex = buffer.indexOf("\n\n")) !== -1) {
        const rawEvent = buffer.slice(0, separatorIndex);
        buffer = buffer.slice(separatorIndex + 2);

        let eventName = "message";
        let dataLine = "";
        for (const line of rawEvent.split("\n")) {
          if (line.startsWith("event:")) eventName = line.slice("event:".length).trim();
          else if (line.startsWith("data:")) dataLine = line.slice("data:".length).trim();
        }
        if (dataLine) {
          yield { event: eventName, data: JSON.parse(dataLine) };
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
