// Proxy to services/api's POST /api/v1/boards/{id}/cards — creates a
// card, appended to the end of its column (see kanban_storage.py).

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

  const upstream = await fetch(
    `${apiBaseUrl}/api/v1/boards/${encodeURIComponent(id)}/cards`,
    {
      method: "POST",
      headers: {
        ...(authorization ? { authorization } : {}),
        "content-type": "application/json",
      },
      body,
    }
  );

  const responseBody = await upstream.text();
  return new Response(responseBody, {
    status: upstream.status,
    headers: { "content-type": "application/json" },
  });
}
