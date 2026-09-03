// Chat management pass — thin DELETE proxy to services/api's
// DELETE /api/v1/chat/sessions/{id}.

function errorResponse(code: string, message: string, status: number) {
  return Response.json({ error: { code, message } }, { status });
}

export async function DELETE(
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
    `${apiBaseUrl}/api/v1/chat/sessions/${encodeURIComponent(id)}`,
    {
      method: "DELETE",
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
