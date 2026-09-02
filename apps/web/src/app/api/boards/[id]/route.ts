// Proxy to services/api's GET /api/v1/boards/{id} — board metadata +
// its cards, ordered by position (the shape the kanban page renders
// directly).

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

  const upstream = await fetch(
    `${apiBaseUrl}/api/v1/boards/${encodeURIComponent(id)}`,
    {
      headers: {
        ...(authorization ? { authorization } : {}),
      },
    }
  );

  const responseBody = await upstream.text();
  return new Response(responseBody, {
    status: upstream.status,
    headers: { "content-type": "application/json" },
  });
}
