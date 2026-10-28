export function plural(count: number, one: string, few: string, many: string) {
  const tens = Math.abs(count) % 100;
  const units = Math.abs(count) % 10;
  if (tens >= 11 && tens <= 14) return many;
  if (units === 1) return one;
  if (units >= 2 && units <= 4) return few;
  return many;
}
