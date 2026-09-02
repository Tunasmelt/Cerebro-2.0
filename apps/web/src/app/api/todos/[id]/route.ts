// Proxy to services/api's /api/v1/todos/{id} — PATCH toggles completed
// (completed_at is derived server-side, never sent by the client),
// DELETE removes the task.

function errorResponse(code: string, message: string, status: number) {
  return Response.json({ error: { code, message } }, { status });
}

export async function PATCH(
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
    `${apiBaseUrl}/api/v1/todos/${encodeURIComponent(id)}`,
    {
      method: "PATCH",
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
    `${apiBaseUrl}/api/v1/todos/${encodeURIComponent(id)}`,
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
