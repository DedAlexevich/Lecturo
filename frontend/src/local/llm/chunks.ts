import type { LocalSegment } from "../storage";

export interface TranscriptChunk {
  start: number;
  end: number;
  text: string;
}

export function splitTranscript(segments: LocalSegment[], limit = 2400): TranscriptChunk[] {
  const chunks: TranscriptChunk[] = [];
  let current: TranscriptChunk | null = null;
  for (const segment of segments) {
    const words = segment.text.trim().split(/\s+/).filter(Boolean);
    for (const word of words) {
      for (let offset = 0; offset < word.length; offset += limit) {
        const part = word.slice(offset, offset + limit);
        if (current && current.text.length + part.length + 1 > limit) {
          chunks.push(current);
          current = null;
        }
        if (!current) current = { start: segment.start, end: segment.end, text: part };
        else {
          current.text += ` ${part}`;
          current.end = segment.end;
        }
      }
    }
  }
  if (current) chunks.push(current);
  return chunks;
}
