const units = ["Б", "КБ", "МБ", "ГБ"];

export function formatBytes(bytes: number) {
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = unit >= 2 && value < 10 ? 1 : 0;
  return `${value.toLocaleString("ru-RU", { maximumFractionDigits: digits })} ${units[unit]}`;
}
