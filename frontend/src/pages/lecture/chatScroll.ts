export type ScrollIntent = "bottom" | "answer" | null;

export const bottomThreshold = 48;

export function scrollIntent(previousCount: number | null, roles: readonly string[]): ScrollIntent {
  if (previousCount === null) return roles.length > 0 ? "bottom" : null;
  if (roles.length <= previousCount) return null;
  return roles[roles.length - 1] === "assistant" ? "answer" : "bottom";
}

export function answerScrollTop(position: {
  scrollTop: number;
  containerTop: number;
  messageTop: number;
  inset: number;
}) {
  return Math.max(0, Math.round(position.scrollTop + position.messageTop - position.containerTop - position.inset));
}

export function hasContentBelow(position: { scrollTop: number; clientHeight: number; scrollHeight: number }) {
  return position.scrollHeight - position.scrollTop - position.clientHeight > bottomThreshold;
}

export function keyboardOverlap(position: { elementBottom: number; viewportTop: number; viewportHeight: number }) {
  return Math.max(0, Math.ceil(position.elementBottom - position.viewportTop - position.viewportHeight));
}
