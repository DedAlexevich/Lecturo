export function formatDuration(seconds: number | null) {
  if (seconds === null) return "—";
  if (seconds <= 0) return "0 мин";
  if (seconds < 60) return "меньше минуты";
  const minutes = Math.round(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours === 0) return `${rest} мин`;
  return rest === 0 ? `${hours} ч` : `${hours} ч ${rest} мин`;
}
