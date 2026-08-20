export function json(data, init = {}) {
  return new Response(JSON.stringify(data), {
    ...init,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Headers": "Content-Type, Authorization, x-admin-token",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      ...(init.headers || {}),
    },
  });
}

export function options() {
  return json({ ok: true });
}

export function readAdminToken(req) {
  const auth = req.headers.get("authorization") || "";
  if (auth.toLowerCase().startsWith("bearer ")) return auth.slice(7).trim();
  return (req.headers.get("x-admin-token") || "").trim();
}

export function requireAdmin(req) {
  const expected = (process.env.ADMIN_TOKEN || "").trim();
  if (!expected) return false;
  return readAdminToken(req) === expected;
}

export async function readJsonBody(req) {
  try {
    return await req.json();
  } catch {
    return {};
  }
}
