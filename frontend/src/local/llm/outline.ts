import type { LocalChapter, LocalSegment } from "../storage/types";

export interface Topic {
  title: string;
  start: number;
}

export interface PartDigest {
  start: number;
  end: number;
  summary: string;
  topics: Topic[];
}

export interface Outline {
  chapters: LocalChapter[];
  summaryMd: string;
}

export const PART_CHARS = 5000;
export const REDUCE_CHARS = 4500;
const TITLE_MAX_LENGTH = 300;

export function formatLine(segment: LocalSegment): string {
  return `[${Math.floor(segment.start)}] ${segment.text.trim()}`;
}

export function splitIntoParts(segments: LocalSegment[], limit = PART_CHARS): LocalSegment[][] {
  const parts: LocalSegment[][] = [];
  let current: LocalSegment[] = [];
  let size = 0;
  for (const segment of segments) {
    const length = formatLine(segment).length + 1;
    if (current.length > 0 && size + length > limit) {
      parts.push(current);
      current = [];
      size = 0;
    }
    current.push(segment);
    size += length;
  }
  if (current.length > 0) {
    if (parts.length > 0 && size < limit / 3) parts[parts.length - 1].push(...current);
    else parts.push(current);
  }
  return parts;
}

export function formatPart(part: LocalSegment[]): string {
  return part.map(formatLine).join("\n");
}

export function parseJson(content: string): Record<string, unknown> | null {
  const text = content.slice(content.indexOf("{"), content.lastIndexOf("}") + 1);
  try {
    const data: unknown = JSON.parse(text);
    return data && typeof data === "object" && !Array.isArray(data) ? (data as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function parseStart(value: unknown): number | null {
  const number = typeof value === "string" ? Number(value) : value;
  return typeof number === "number" && Number.isFinite(number) ? number : null;
}

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

export function parseTopics(items: unknown): Topic[] {
  if (!Array.isArray(items)) return [];
  const topics: Topic[] = [];
  for (const item of items) {
    if (!item || typeof item !== "object") continue;
    const record = item as Record<string, unknown>;
    const title = text(record.title);
    const start = parseStart(record.start);
    if (title && start !== null) topics.push({ title, start });
  }
  return topics;
}

export function toDigest(part: LocalSegment[], data: Record<string, unknown> | null): PartDigest {
  return {
    start: part[0].start,
    end: part[part.length - 1].end,
    summary: text(data?.summary),
    topics: parseTopics(data?.topics),
  };
}

export function digestRequest(title: string, digests: PartDigest[]): string {
  return JSON.stringify({
    title,
    parts: digests.map((digest) => ({
      start: Math.floor(digest.start),
      end: Math.floor(digest.end),
      summary: digest.summary,
      topics: digest.topics.map((topic) => ({ title: topic.title, start: Math.floor(topic.start) })),
    })),
  });
}

export function groupDigests(title: string, digests: PartDigest[], limit = REDUCE_CHARS): PartDigest[][] {
  const groups: PartDigest[][] = [];
  let current: PartDigest[] = [];
  for (const digest of digests) {
    if (current.length > 0 && digestRequest(title, [...current, digest]).length > limit) {
      groups.push(current);
      current = [];
    }
    current.push(digest);
  }
  if (current.length > 0) groups.push(current);
  return groups;
}

function nearest(start: number, starts: number[]): number {
  return starts.reduce((best, value) => (Math.abs(value - start) < Math.abs(best - start) ? value : best), starts[0]);
}

function fallbackTitle(digest: PartDigest, number: number): string {
  return (digest.topics[0]?.title ?? `Часть ${number}`).slice(0, TITLE_MAX_LENGTH);
}

export function buildChapters(raw: unknown[], segments: LocalSegment[], digests: PartDigest[]): LocalChapter[] {
  if (segments.length === 0) return [];
  const starts = segments.map((segment) => segment.start);
  const drafts = new Map<number, { title: string; summary: string }>();
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const record = item as Record<string, unknown>;
    const title = text(record.title).slice(0, TITLE_MAX_LENGTH);
    const start = parseStart(record.start);
    if (!title || start === null) continue;
    const snapped = nearest(start, starts);
    if (!drafts.has(snapped)) drafts.set(snapped, { title, summary: text(record.summary) });
  }
  if (drafts.size === 0) {
    digests.forEach((digest, index) => {
      if (!drafts.has(digest.start)) drafts.set(digest.start, { title: fallbackTitle(digest, index + 1), summary: digest.summary });
    });
  }
  const ordered = [...drafts.entries()].sort((a, b) => a[0] - b[0]);
  const lectureEnd = segments[segments.length - 1].end;
  return ordered.map(([start, draft], index) => ({
    title: draft.title,
    start: index === 0 ? starts[0] : start,
    end: index + 1 < ordered.length ? ordered[index + 1][0] : lectureEnd,
    summary: draft.summary,
  }));
}

export function buildOutline(
  reductions: (Record<string, unknown> | null)[],
  segments: LocalSegment[],
  digests: PartDigest[],
): Outline {
  const raw = reductions.flatMap((data) => (Array.isArray(data?.chapters) ? data.chapters : []));
  const chapters = buildChapters(raw, segments, digests);
  const summaries = reductions.map((data) => text(data?.summary_md)).filter(Boolean);
  const summaryMd = summaries.length > 0
    ? summaries.join("\n\n")
    : chapters.map((chapter) => `## ${chapter.title}${chapter.summary ? `\n\n${chapter.summary}` : ""}`).join("\n\n");
  return { chapters, summaryMd };
}
