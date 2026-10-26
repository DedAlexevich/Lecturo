import type { Location } from "react-router";

export function redirectTarget(state: unknown): string {
  const from = (state as { from?: Location } | null)?.from;
  if (!from || from.pathname === "/login" || from.pathname === "/register") return "/";
  return `${from.pathname}${from.search}${from.hash}`;
}
