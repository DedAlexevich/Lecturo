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
    const words = segment.text.matchAll(/\S+/g);
    for (const word of words) {
      for (let offset = 0; offset < word[0].length; offset += limit) {
        const part = word[0].slice(offset, offset + limit);
        const duration = Math.max(0, segment.end - segment.start);
        const start = segment.start + duration * (word.index + offset) / segment.text.length;
        const end = segment.start + duration * (word.index + offset + part.length) / segment.text.length;
        if (current && current.text.length + part.length + 1 > limit) {
          chunks.push(current);
          current = null;
        }
        if (!current) current = { start, end, text: part };
        else {
          current.text += ` ${part}`;
          current.end = end;
        }
      }
    }
  }
  if (current) chunks.push(current);
  return chunks;
}
