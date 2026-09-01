// Streaming proxy to services/api's /api/v1/chat/sessions/{id}/stream
// (Stage 1.7). Unlike this app's other proxy routes, this one must NOT
// buffer the response with `.text()` — the whole point of SSE is that
// events (retrieval, then tokens, then citations, then done) arrive
// incrementally, and Stage 2.4's graph pulse needs to react to the
// `retrieval` event as soon as it lands, not after the full answer has
// finished streaming. `upstream.body` is already a ReadableStream, so
// it's passed straight through as this response's body.

function errorResponse(code: string, message: string, status: number) {
  return Response.json({ error: { code, message } }, { status });
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const apiBaseUrl = process.env.API_BASE_URL;
  if (!apiBaseUrl) {
    return errorResponse("server_misconfigured", "API backend is not configured", 500);
  }

  const { id } = await params;
  const authorization = request.headers.get("authorization");
  const body = await request.text();

  const upstream = await fetch(`${apiBaseUrl}/api/v1/chat/sessions/${id}/stream`, {
    method: "POST",
    headers: {
      ...(authorization ? { authorization } : {}),
      "content-type": "application/json",
    },
    body,
  });

  if (!upstream.ok) {
    const errorBody = await upstream.text();
    return new Response(errorBody, {
      status: upstream.status,
      headers: { "content-type": "application/json" },
    });
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "content-type": "text/event-stream",
      "cache-control": "no-cache",
      connection: "keep-alive",
    },
  });
}
