import type { components } from "../../api/schema";

export type LocalSegment = components["schemas"]["SegmentOut"];
export type LocalChapter = components["schemas"]["ChapterOut"];
export type LocalResultPayload = components["schemas"]["LocalResultIn"];

export interface LocalLecture {
  id: string;
  title: string;
  createdAt: number;
  durationSec: number;
  language: string;
  model: string;
  segments: LocalSegment[];
  chapters: LocalChapter[];
  summaryMd: string | null;
}

export type NewLocalLecture = Omit<LocalLecture, "id" | "createdAt" | "chapters" | "summaryMd"> &
  Partial<Pick<LocalLecture, "chapters" | "summaryMd">>;

export interface LocalLectureSummary {
  id: string;
  title: string;
  createdAt: number;
  durationSec: number;
  language: string;
  model: string;
  segmentCount: number;
}
