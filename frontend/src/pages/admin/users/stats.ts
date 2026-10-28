export const maxPeriodDays = 366;

export type Period = { from: string; to: string };

const isoDate = /^\d{4}-\d{2}-\d{2}$/;

export function toIsoDate(date: Date) {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

function parseIsoDate(value: string) {
  if (!isoDate.test(value)) return null;
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCMonth() === month - 1 && date.getUTCDate() === day ? date : null;
}

export function lastDays(days: number, today: Date): Period {
  const start = new Date(today);
  start.setDate(start.getDate() - (days - 1));
  return { from: toIsoDate(start), to: toIsoDate(today) };
}

export function periodLength(period: Period) {
  const from = parseIsoDate(period.from);
  const to = parseIsoDate(period.to);
  if (!from || !to) return null;
  return Math.round((to.getTime() - from.getTime()) / 86_400_000) + 1;
}

export function periodProblem(period: Period) {
  const length = periodLength(period);
  if (length === null) return "Укажите обе даты";
  if (length < 1) return "Начало периода позже конца";
  if (length > maxPeriodDays) return `Период не длиннее ${maxPeriodDays} дней`;
  return null;
}

export function readPeriod(params: URLSearchParams, fallback: Period): Period {
  const from = params.get("from");
  const to = params.get("to");
  if (from === null || to === null) return fallback;
  const period = { from, to };
  return periodProblem(period) === null ? period : fallback;
}

const steps = [1, 2, 2.5, 5, 10];

export function niceScale(max: number, tickCount = 4) {
  if (!(max > 0)) return { top: tickCount, ticks: Array.from({ length: tickCount + 1 }, (_, index) => index) };
  const rough = max / tickCount;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const step =
    steps.map((candidate) => candidate * magnitude).find((candidate) => candidate >= rough && Number.isInteger(candidate)) ??
    10 * magnitude;
  const wholeStep = Math.max(1, step);
  return {
    top: wholeStep * tickCount,
    ticks: Array.from({ length: tickCount + 1 }, (_, index) => index * wholeStep),
  };
}

export function labelEvery(dayCount: number, maxLabels = 7) {
  return Math.max(1, Math.ceil(dayCount / maxLabels));
}
