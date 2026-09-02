// Thin GET proxy to services/api's /api/v1/graph/edges (Stage 2.2).
// Stage 5.4 — forwards ?include=associative through unchanged.

function errorResponse(code: string, message: string, status: number) {
  return Response.json({ error: { code, message } }, { status });
}

export async function GET(request: Request) {
  const apiBaseUrl = process.env.API_BASE_URL;
  if (!apiBaseUrl) {
    return errorResponse("server_misconfigured", "API backend is not configured", 500);
  }

  const authorization = request.headers.get("authorization");
  const { search } = new URL(request.url);

  const upstream = await fetch(`${apiBaseUrl}/api/v1/graph/edges${search}`, {
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
