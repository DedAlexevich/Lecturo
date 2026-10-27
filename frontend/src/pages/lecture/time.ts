export function formatDuration(totalSeconds: number) {
  const minutes = Math.max(1, Math.round(totalSeconds / 60));
  const hours = Math.floor(minutes / 60);
  if (hours === 0) return `${minutes} мин`;
  const rest = minutes % 60;
  return rest === 0 ? `${hours} ч` : `${hours} ч ${rest} мин`;
}

export function parseStartTime(value: string | null) {
  if (value === null || value.trim() === "") return null;
  const seconds = Number(value);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
}

export function findActiveSegment(segments: { start: number }[], time: number) {
  let low = 0;
  let high = segments.length - 1;
  let found = -1;
  while (low <= high) {
    const middle = (low + high) >> 1;
    if (segments[middle].start <= time) {
      found = middle;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  return found;
}

export type TranscriptSentence<S> = {
  start: number;
  end: number;
  text: string;
  segments: S[];
};

const SENTENCE_END = /[.!?…]["»”')\]]*$/;
const SENTENCE_PAUSE_SEC = 1.5;
const SENTENCE_MAX_SEC = 25;

export function joinSentences<S extends { start: number; end: number; text: string }>(
  segments: S[],
  chapters: { start: number }[] = [],
): TranscriptSentence<S>[] {
  const sentences: TranscriptSentence<S>[] = [];
  let current: TranscriptSentence<S> | null = null;
  let currentChapter = -1;
  for (const segment of segments) {
    const text = segment.text.trim();
    const chapter = findActiveSegment(chapters, segment.start);
    const continues =
      current !== null &&
      chapter === currentChapter &&
      !SENTENCE_END.test(current.text) &&
      segment.start - current.end <= SENTENCE_PAUSE_SEC &&
      Math.max(segment.end, segment.start) - current.start <= SENTENCE_MAX_SEC;
    if (continues && current !== null) {
      current.end = Math.max(current.end, segment.end);
      current.text = [current.text, text].filter(Boolean).join(" ");
      current.segments.push(segment);
    } else {
      current = { start: segment.start, end: segment.end, text, segments: [segment] };
      sentences.push(current);
      currentChapter = chapter;
    }
  }
  return sentences;
}

export type TranscriptRow<S, C> =
  | { kind: "chapter"; chapter: C; chapterIndex: number }
  | { kind: "segment"; segment: S; segmentIndex: number };

export function groupTranscript<S extends { start: number }, C extends { start: number }>(
  segments: S[],
  chapters: C[],
): TranscriptRow<S, C>[] {
  const rows: TranscriptRow<S, C>[] = [];
  let lastChapter = -1;
  segments.forEach((segment, segmentIndex) => {
    const chapterIndex = findActiveSegment(chapters, segment.start);
    if (chapterIndex >= 0 && chapterIndex !== lastChapter) {
      rows.push({ kind: "chapter", chapter: chapters[chapterIndex], chapterIndex });
      lastChapter = chapterIndex;
    }
    rows.push({ kind: "segment", segment, segmentIndex });
  });
  return rows;
}
