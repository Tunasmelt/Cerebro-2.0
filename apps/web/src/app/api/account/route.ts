// Proxy to services/api's DELETE /api/v1/account — wipes all
// application data the caller owns. Does not delete the auth account
// itself (see account_storage.py's module docstring).

function errorResponse(code: string, message: string, status: number) {
  return Response.json({ error: { code, message } }, { status });
}

export async function DELETE(request: Request) {
  const apiBaseUrl = process.env.API_BASE_URL;
  if (!apiBaseUrl) {
    return errorResponse("server_misconfigured", "API backend is not configured", 500);
  }

  const authorization = request.headers.get("authorization");

  const upstream = await fetch(`${apiBaseUrl}/api/v1/account`, {
    method: "DELETE",
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
