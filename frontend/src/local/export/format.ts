import type { LocalLecture } from "../storage/types";

export type ExportFormat = "srt" | "vtt" | "md";

export interface ExportFile {
  name: string;
  mime: string;
  content: string;
}

export interface Cue {
  start: number;
  end: number;
  lines: string[];
}

const LINE_LIMIT = 42;
const CUE_LINES = 2;
const MIN_CUE_SECONDS = 0.001;

export function wrapText(text: string, limit = LINE_LIMIT): string[] {
  const words = text.split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let current = "";
  for (const word of words) {
    if (!current) {
      current = word;
    } else if (current.length + 1 + word.length <= limit) {
      current += ` ${word}`;
    } else {
      lines.push(current);
      current = word;
    }
  }
  if (current) lines.push(current);
  return lines;
}

export function buildCues(segments: LocalLecture["segments"]): Cue[] {
  const cues: Cue[] = [];
  for (const segment of segments) {
    const lines = wrapText(segment.text);
    if (lines.length === 0) continue;
    const start = Math.max(0, segment.start);
    const end = Math.max(segment.end, start + MIN_CUE_SECONDS);
    const groups: string[][] = [];
    for (let index = 0; index < lines.length; index += CUE_LINES) groups.push(lines.slice(index, index + CUE_LINES));
    const weights = groups.map((group) => group.join(" ").length);
    const total = weights.reduce((sum, weight) => sum + weight, 0);
    let cursor = start;
    let consumed = 0;
    groups.forEach((group, index) => {
      consumed += weights[index];
      const groupEnd = index === groups.length - 1 ? end : start + ((end - start) * consumed) / total;
      cues.push({ start: cursor, end: groupEnd, lines: group });
      cursor = groupEnd;
    });
  }
  return cues;
}

function pad(value: number, length = 2) {
  return String(value).padStart(length, "0");
}

export function formatClock(seconds: number, separator: "," | "."): string {
  const totalMs = Math.round(Math.max(0, seconds) * 1000);
  const ms = totalMs % 1000;
  const totalSeconds = Math.floor(totalMs / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  return `${pad(hours)}:${pad(minutes)}:${pad(totalSeconds % 60)}${separator}${pad(ms, 3)}`;
}

export function formatMark(seconds: number): string {
  const total = Math.floor(Math.max(0, seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = total % 60;
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(rest)}` : `${pad(minutes)}:${pad(rest)}`;
}

export function toSrt(lecture: Pick<LocalLecture, "segments">): string {
  return buildCues(lecture.segments)
    .map((cue, index) => `${index + 1}\n${formatClock(cue.start, ",")} --> ${formatClock(cue.end, ",")}\n${cue.lines.join("\n")}\n`)
    .join("\n");
}

function escapeVtt(line: string) {
  return line.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function toVtt(lecture: Pick<LocalLecture, "segments">): string {
  const body = buildCues(lecture.segments)
    .map((cue) => `${formatClock(cue.start, ".")} --> ${formatClock(cue.end, ".")}\n${cue.lines.map(escapeVtt).join("\n")}\n`)
    .join("\n");
  return body ? `WEBVTT\n\n${body}` : "WEBVTT\n";
}

export function toMarkdown(lecture: Pick<LocalLecture, "title" | "durationSec" | "segments" | "chapters" | "summaryMd">): string {
  const parts = [`# ${lecture.title.trim() || "Лекция"}`, `Длительность: ${formatMark(lecture.durationSec)}`];
  if (lecture.summaryMd?.trim()) parts.push(`## Конспект\n\n${lecture.summaryMd.trim()}`);
  if (lecture.chapters.length > 0) {
    const chapters = lecture.chapters.map(
      (chapter) => `- **${formatMark(chapter.start)}** ${chapter.title}${chapter.summary ? `. ${chapter.summary}` : ""}`,
    );
    parts.push(`## Главы\n\n${chapters.join("\n")}`);
  }
  const lines = lecture.segments
    .map((segment) => ({ start: segment.start, text: segment.text.replace(/\s+/g, " ").trim() }))
    .filter((segment) => segment.text)
    .map((segment) => `**${formatMark(segment.start)}** ${segment.text}`);
  parts.push(`## Расшифровка\n\n${lines.join("\n\n")}`);
  return `${parts.join("\n\n")}\n`;
}

export function exportFileName(title: string, format: ExportFormat): string {
  const base = title
    .replace(/[\\/:*?"<>|\u0000-\u001f]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^\.+|\.+$/g, "")
    .slice(0, 80)
    .trim();
  return `${base || "lecture"}.${format}`;
}

const MIME: Record<ExportFormat, string> = {
  srt: "application/x-subrip;charset=utf-8",
  vtt: "text/vtt;charset=utf-8",
  md: "text/markdown;charset=utf-8",
};

export function buildExport(lecture: LocalLecture, format: ExportFormat): ExportFile {
  const content = format === "srt" ? toSrt(lecture) : format === "vtt" ? toVtt(lecture) : toMarkdown(lecture);
  return { name: exportFileName(lecture.title, format), mime: MIME[format], content };
}
