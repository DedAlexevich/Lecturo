const dateTime = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });
const dateOnly = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", year: "numeric" });
const shortDate = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", year: "numeric" });
const relative = new Intl.RelativeTimeFormat("ru-RU", { numeric: "auto" });
const rubles = new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB", maximumFractionDigits: 2, minimumFractionDigits: 0 });

export function formatDuration(seconds: number) {
  const minutes = Math.max(0, Math.floor(seconds / 60));
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours === 0) return `${rest} мин`;
  if (rest === 0) return `${hours} ч`;
  return `${hours} ч ${rest} мин`;
}

export function formatDateTime(value: string) {
  return dateTime.format(new Date(value)).replace(",", " в");
}

export function formatDate(value: string) {
  return dateOnly.format(new Date(value)).replace(" г.", "");
}

export function formatShortDate(value: string) {
  return shortDate.format(new Date(value)).replace(" г.", "");
}

export function formatRelative(value: string, now = Date.now()) {
  const diff = new Date(value).getTime() - now;
  const hours = Math.round(diff / 3_600_000);
  if (Math.abs(hours) < 24) {
    if (Math.abs(hours) < 1) return relative.format(Math.round(diff / 60_000), "minute");
    return relative.format(hours, "hour");
  }
  return relative.format(Math.round(diff / 86_400_000), "day");
}

export function formatRubles(amount: number) {
  return rubles.format(amount);
}
