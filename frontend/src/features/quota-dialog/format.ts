const resetTime = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });
const relative = new Intl.RelativeTimeFormat("ru-RU", { numeric: "auto" });

export function lectureSeconds(durationSec: number | null) {
  return durationSec === null ? 0 : Math.ceil(durationSec);
}

export function formatMinutes(seconds: number) {
  const minutes = Math.ceil(Math.max(0, seconds) / 60);
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (minutes === 0) return "0 мин";
  if (hours === 0) return `${rest} мин`;
  if (rest === 0) return `${hours} ч`;
  return `${hours} ч ${rest} мин`;
}

export function formatReset(value: string, now = Date.now()) {
  const date = new Date(value);
  const diff = date.getTime() - now;
  const days = Math.round(diff / 86_400_000);
  const hours = Math.round(diff / 3_600_000);
  const when = Math.abs(hours) < 24 ? relative.format(Math.max(1, hours), "hour") : relative.format(days, "day");
  return `${resetTime.format(date).replace(",", " в")}, ${when}`;
}

export function lecturesWord(count: number) {
  const tens = count % 100;
  const ones = count % 10;
  if (tens >= 11 && tens <= 14) return "лекций";
  if (ones === 1) return "лекция";
  if (ones >= 2 && ones <= 4) return "лекции";
  return "лекций";
}
