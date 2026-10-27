export function nextClipIndex(previous: number | null, count: number): number | null {
  if (count <= 0) return null;
  if (previous === null || !Number.isInteger(previous) || previous < 0) return 0;
  return (previous + 1) % count;
}

export function parseStoredIndex(value: string | null): number | null {
  if (value === null || !/^\d+$/.test(value)) return null;
  return Number(value);
}

export function parseStoredMode(value: string | null): boolean {
  return value === "on";
}
