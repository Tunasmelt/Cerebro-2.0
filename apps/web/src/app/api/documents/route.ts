// Thin JSON proxy — the signed-URL flow means file bytes never pass
// through here at all (Vercel hard-caps function bodies well under the
// documented 50MB; see architecture-and-security.md §1). This route only
// forwards the small "authorize an upload" request/response.

function errorResponse(code: string, message: string, status: number) {
  return Response.json({ error: { code, message } }, { status });
}

export async function POST(request: Request) {
  const apiBaseUrl = process.env.API_BASE_URL;
  if (!apiBaseUrl) {
    return errorResponse(
      "server_misconfigured",
      "Upload backend is not configured",
      500
    );
  }

  const authorization = request.headers.get("authorization");
  const body = await request.text();

  const upstream = await fetch(`${apiBaseUrl}/api/v1/documents/upload-init`, {
    method: "POST",
    headers: {
      ...(authorization ? { authorization } : {}),
      "content-type": "application/json",
    },
    body,
  });

  const responseBody = await upstream.text();
  return new Response(responseBody, {
    status: upstream.status,
    headers: { "content-type": "application/json" },
  });
}

export async function GET(request: Request) {
  const apiBaseUrl = process.env.API_BASE_URL;
  if (!apiBaseUrl) {
    return errorResponse(
      "server_misconfigured",
      "Upload backend is not configured",
      500
    );
  }

  const authorization = request.headers.get("authorization");

  const upstream = await fetch(`${apiBaseUrl}/api/v1/documents`, {
    method: "GET",
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
