// Thin GET proxy to services/api's /api/v1/_probe (Stage 0.5's throwaway
// auth-proof route). Stage 1.6 reuses it as the live proof that a real
// Supabase session established through the sign-in/sign-up UI actually
// authenticates requests to services/api — not a separate token obtained
// some other way.

function errorResponse(code: string, message: string, status: number) {
  return Response.json({ error: { code, message } }, { status });
}

export async function GET(request: Request) {
  const apiBaseUrl = process.env.API_BASE_URL;
  if (!apiBaseUrl) {
    return errorResponse("server_misconfigured", "API backend is not configured", 500);
  }

  const authorization = request.headers.get("authorization");

  const upstream = await fetch(`${apiBaseUrl}/api/v1/_probe`, {
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
