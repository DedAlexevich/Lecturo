export type HighlightPart = { text: string; marked: boolean };

function stem(word: string) {
  if (word.length >= 6) return word.slice(0, -2);
  if (word.length === 5) return word.slice(0, -1);
  return word;
}

function escape(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function buildMatcher(query: string) {
  const stems = query
    .toLowerCase()
    .split(/[^\p{L}\p{N}]+/u)
    .filter((word) => word.length >= 2)
    .map((word) => escape(stem(word)));
  if (stems.length === 0) return null;
  const unique = [...new Set(stems)].sort((a, b) => b.length - a.length);
  return new RegExp(`(^|[^\\p{L}\\p{N}])((?:${unique.join("|")})[\\p{L}\\p{N}]*)`, "giu");
}

export function splitHighlights(text: string, matcher: RegExp | null): HighlightPart[] {
  if (matcher === null) return [{ text, marked: false }];
  const parts: HighlightPart[] = [];
  let last = 0;
  for (const match of text.matchAll(matcher)) {
    const start = (match.index ?? 0) + match[1].length;
    if (start > last) parts.push({ text: text.slice(last, start), marked: false });
    parts.push({ text: match[2], marked: true });
    last = start + match[2].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last), marked: false });
  return parts;
}
