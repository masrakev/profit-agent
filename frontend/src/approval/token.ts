/** The approval token in the email link's fragment (`#token=<payload>.<signature>`). */
export function approvalToken(hash: string): string | null {
  const token = new URLSearchParams(hash.replace(/^#/, "")).get("token");
  return token && /^[A-Za-z0-9_.-]{16,600}$/.test(token) ? token : null;
}
