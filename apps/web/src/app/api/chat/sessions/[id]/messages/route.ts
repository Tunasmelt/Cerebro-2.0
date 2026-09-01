// Thin GET proxy to services/api's /api/v1/chat/sessions/{id}/messages
// (Stage 2.4) — a past conversation's history, with each message's
// retrieved_document_ids already resolved server-side, for replaying
// the graph pulse.

function errorResponse(code: string, message: string, status: number) {
  return Response.json({ error: { code, message } }, { status });
}

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const apiBaseUrl = process.env.API_BASE_URL;
  if (!apiBaseUrl) {
    return errorResponse("server_misconfigured", "API backend is not configured", 500);
  }

  const { id } = await params;
  const authorization = request.headers.get("authorization");

  const upstream = await fetch(`${apiBaseUrl}/api/v1/chat/sessions/${id}/messages`, {
    headers: {
      ...(authorization ? { authorization } : {}),
    },
  });

  const responseBody = await upstream.text();
  return new Response(responseBody, {
    status: upstream.status,
    headers: { "content-type": "application/json" },
  });
}
