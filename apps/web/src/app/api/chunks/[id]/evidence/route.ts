function errorResponse(code: string, message: string, status: number) {
  return Response.json({ error: { code, message } }, { status });
}

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const apiBaseUrl = process.env.API_BASE_URL;
  if (!apiBaseUrl) return errorResponse("server_misconfigured", "API backend is not configured", 500);
  const { id } = await params;
  const page = new URL(request.url).searchParams.get("page");
  const authorization = request.headers.get("authorization");
  const upstream = await fetch(
    `${apiBaseUrl}/api/v1/chunks/${encodeURIComponent(id)}/evidence${page ? `?page=${encodeURIComponent(page)}` : ""}`,
    { headers: authorization ? { authorization } : {} }
  );
  return new Response(await upstream.text(), {
    status: upstream.status,
    headers: { "content-type": "application/json" },
  });
}
