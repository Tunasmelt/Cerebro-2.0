const MAX_UPLOAD_BYTES = 50 * 1024 * 1024; // 50MB — the guaranteed enforcement
// point per architecture-and-security.md §3: an oversized upload must never
// reach Render at all, not just get rejected once it arrives.

function errorResponse(code: string, message: string, status: number) {
  return Response.json({ error: { code, message } }, { status });
}

export async function POST(request: Request) {
  const contentLength = request.headers.get("content-length");
  if (contentLength && Number(contentLength) > MAX_UPLOAD_BYTES) {
    return errorResponse(
      "file_too_large",
      "File exceeds the 50MB upload limit",
      413
    );
  }

  if (!request.body) {
    return errorResponse("empty_body", "No file body provided", 400);
  }

  // Content-Length can be absent or spoofed, so this is the actual
  // enforcement: buffer while counting bytes and bail the instant the cap
  // is crossed, before any request to the backend is ever made.
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > MAX_UPLOAD_BYTES) {
      await reader.cancel();
      return errorResponse(
        "file_too_large",
        "File exceeds the 50MB upload limit",
        413
      );
    }
    chunks.push(value);
  }
  const body = Buffer.concat(chunks);

  const apiBaseUrl = process.env.API_BASE_URL;
  if (!apiBaseUrl) {
    return errorResponse(
      "server_misconfigured",
      "Upload backend is not configured",
      500
    );
  }

  const authorization = request.headers.get("authorization");
  const contentType = request.headers.get("content-type");
  const upstream = await fetch(`${apiBaseUrl}/api/v1/documents`, {
    method: "POST",
    headers: {
      ...(authorization ? { authorization } : {}),
      ...(contentType ? { "content-type": contentType } : {}),
    },
    body,
  });

  const responseBody = await upstream.text();
  return new Response(responseBody, {
    status: upstream.status,
    headers: { "content-type": "application/json" },
  });
}
