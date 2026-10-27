function plural(count: number, one: string, few: string, many: string) {
  const tens = count % 100;
  const units = count % 10;
  if (tens >= 11 && tens <= 14) return many;
  if (units === 1) return one;
  if (units >= 2 && units <= 4) return few;
  return many;
}

export function ticketsCount(count: number) {
  return `${count} ${plural(count, "билет", "билета", "билетов")}`;
}

export function definitionsCount(count: number) {
  return `${count} ${plural(count, "определение", "определения", "определений")}`;
}
