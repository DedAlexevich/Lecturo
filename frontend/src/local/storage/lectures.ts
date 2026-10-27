import { LECTURES_STORE, openDb, requestResult, transactionDone } from "./db";
import type { LocalLecture, LocalLectureSummary, LocalResultPayload, NewLocalLecture } from "./types";

function createId() {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function toSummary(lecture: LocalLecture): LocalLectureSummary {
  return {
    id: lecture.id,
    title: lecture.title,
    createdAt: lecture.createdAt,
    durationSec: lecture.durationSec,
    language: lecture.language,
    model: lecture.model,
    segmentCount: lecture.segments.length,
  };
}

export async function saveLocalLecture(input: NewLocalLecture): Promise<LocalLecture> {
  const lecture: LocalLecture = {
    ...input,
    id: createId(),
    createdAt: Date.now(),
    chapters: input.chapters ?? [],
    summaryMd: input.summaryMd ?? null,
  };
  const db = await openDb();
  const transaction = db.transaction(LECTURES_STORE, "readwrite");
  transaction.objectStore(LECTURES_STORE).put(lecture);
  await transactionDone(transaction);
  return lecture;
}

export async function getLocalLecture(id: string): Promise<LocalLecture | null> {
  const db = await openDb();
  const result = await requestResult<LocalLecture | undefined>(
    db.transaction(LECTURES_STORE).objectStore(LECTURES_STORE).get(id),
  );
  return result ?? null;
}

export async function listLocalLectures(): Promise<LocalLectureSummary[]> {
  const db = await openDb();
  const all = await requestResult<LocalLecture[]>(db.transaction(LECTURES_STORE).objectStore(LECTURES_STORE).getAll());
  return all.sort((a, b) => b.createdAt - a.createdAt).map(toSummary);
}

export async function deleteLocalLecture(id: string): Promise<void> {
  const db = await openDb();
  const transaction = db.transaction(LECTURES_STORE, "readwrite");
  transaction.objectStore(LECTURES_STORE).delete(id);
  await transactionDone(transaction);
}

export function toLocalResultPayload(lecture: LocalLecture): LocalResultPayload {
  return {
    title: lecture.title,
    duration_sec: lecture.durationSec,
    language: lecture.language,
    model: lecture.model,
    segments: lecture.segments,
    chapters: lecture.chapters,
    summary_md: lecture.summaryMd,
  };
}

export async function saveLocalOutline(
  id: string,
  outline: Pick<LocalLecture, "chapters" | "summaryMd">,
): Promise<LocalLecture | null> {
  const db = await openDb();
  const transaction = db.transaction(LECTURES_STORE, "readwrite");
  const store = transaction.objectStore(LECTURES_STORE);
  const request = store.get(id);
  let updated: LocalLecture | null = null;
  request.onsuccess = () => {
    const lecture = request.result as LocalLecture | undefined;
    if (!lecture) return;
    updated = { ...lecture, chapters: outline.chapters, summaryMd: outline.summaryMd };
    store.put(updated);
  };
  await transactionDone(transaction);
  return updated;
}

export async function markLocalLectureSynced(id: string, userId: string, lectureId: string): Promise<void> {
  const db = await openDb();
  const transaction = db.transaction(LECTURES_STORE, "readwrite");
  const store = transaction.objectStore(LECTURES_STORE);
  const request = store.get(id);
  request.onsuccess = () => {
    const lecture = request.result as LocalLecture | undefined;
    if (lecture) store.put({ ...lecture, syncedLectures: { ...lecture.syncedLectures, [userId]: lectureId } });
  };
  await transactionDone(transaction);
}
