// Thin GET proxy to services/api's /api/v1/documents/{id}/seal-salt —
// the salt an unlock attempt needs to re-derive the passphrase key
// against, before it can call /unlock at all. Not secret (see the
// backend's own get_salt docstring) — a 404 just means nothing is
// sealed for this document.

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
    `${apiBaseUrl}/api/v1/documents/${encodeURIComponent(id)}/seal-salt`,
    {
      method: "GET",
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
