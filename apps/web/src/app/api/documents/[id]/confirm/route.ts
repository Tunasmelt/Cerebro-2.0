function errorResponse(code: string, message: string, status: number) {
  return Response.json({ error: { code, message } }, { status });
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const apiBaseUrl = process.env.API_BASE_URL;
  if (!apiBaseUrl) {
    return errorResponse(
      "server_misconfigured",
      "Upload backend is not configured",
      500
    );
  }

  const { id } = await params;
  const authorization = request.headers.get("authorization");

  const upstream = await fetch(
    `${apiBaseUrl}/api/v1/documents/${encodeURIComponent(id)}/upload-confirm`,
    {
      method: "POST",
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
