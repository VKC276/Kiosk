/** Samma 10-kort inom detta fönster = retry av osäkert svar, inte nytt klipp. */
export const CLIP_DEBOUNCE_SECONDS = 30;

export function isRecentlyClipped(
  lastClippedAt: string | null | undefined,
  debounceSeconds: number = CLIP_DEBOUNCE_SECONDS,
  nowMs: number = Date.now(),
): boolean {
  if (!lastClippedAt) return false;
  // D1 datetime('now') → "YYYY-MM-DD HH:MM:SS" (UTC). Tolka som UTC.
  const normalized = String(lastClippedAt).trim().replace(" ", "T");
  const withZone = /Z$|[+-]\d{2}:?\d{2}$/.test(normalized)
    ? normalized
    : `${normalized}Z`;
  const clippedMs = Date.parse(withZone);
  if (!Number.isFinite(clippedMs)) return false;
  return nowMs - clippedMs < debounceSeconds * 1000;
}
