export type LinkStep = "open" | "refresh" | "fail";

export function nextLinkStep(status: number, refreshed: boolean): LinkStep {
  if (status >= 200 && status < 300) return "open";
  if (status === 401 && !refreshed) return "refresh";
  return "fail";
}
