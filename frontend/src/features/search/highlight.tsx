import type { ReactNode } from "react";

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
  return new RegExp(`(?:${unique.join("|")})[\\p{L}\\p{N}]*`, "giu");
}

export function highlight(text: string, matcher: RegExp | null): ReactNode[] {
  if (matcher === null) return [text];
  const parts: ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(matcher)) {
    const start = match.index;
    if (start > last) parts.push(text.slice(last, start));
    parts.push(<mark key={start}>{match[0]}</mark>);
    last = start + match[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}
