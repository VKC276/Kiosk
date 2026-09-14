export function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) {
    let dummy = 0;
    for (let i = 0; i < b.length; i++) dummy |= b.charCodeAt(i);
    return dummy === -1;
  }
  let mismatch = 0;
  for (let i = 0; i < a.length; i++) {
    mismatch |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return mismatch === 0;
}

export function bearerToken(request: Request): string {
  const header = request.headers.get("Authorization") || "";
  const match = header.match(/^Bearer\s+(.+)$/i);
  if (match) return match[1].trim();
  return request.headers.get("X-Kiosk-Token")?.trim() || "";
}

export function requireToken(request: Request, expected: string | undefined, name: string): Response | null {
  if (!expected) {
    return Response.json(
      { ok: false, error: `${name} is not configured on the Worker` },
      { status: 500 },
    );
  }
  const got = bearerToken(request);
  if (!got || !timingSafeEqual(got, expected)) {
    return Response.json({ ok: false, error: "unauthorized" }, { status: 401 });
  }
  return null;
}
