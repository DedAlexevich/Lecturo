import type { ReactNode } from "react";
import { splitHighlights } from "./matcher";

export function highlight(text: string, matcher: RegExp | null): ReactNode[] {
  let offset = 0;
  return splitHighlights(text, matcher).map((part) => {
    const key = offset;
    offset += part.text.length;
    return part.marked ? <mark key={key}>{part.text}</mark> : part.text;
  });
}
