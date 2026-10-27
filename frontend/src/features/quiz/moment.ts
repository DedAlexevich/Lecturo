export function momentLink(lectureId: string, seconds: number) {
  return `/lectures/${lectureId}?t=${Math.floor(seconds)}`;
}

export const fromQuizState = { fromQuiz: true };

export function cameFromQuiz(state: unknown) {
  return typeof state === "object" && state !== null && "fromQuiz" in state && state.fromQuiz === true;
}
