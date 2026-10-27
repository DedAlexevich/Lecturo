import { createId } from "../../lib/id";
import { LECTURES_STORE, MEDIA_STORE, openDb, requestResult, transactionDone } from "./db";
import type { LocalLecture, LocalLectureSummary, LocalResultPayload, NewLocalLecture } from "./types";

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
  const transaction = db.transaction([LECTURES_STORE, MEDIA_STORE], "readwrite");
  transaction.objectStore(LECTURES_STORE).delete(id);
  transaction.objectStore(MEDIA_STORE).delete(id);
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

export async function updateLocalNotes(id: string, chapters: LocalLecture["chapters"], summaryMd: string): Promise<LocalLecture> {
  const db = await openDb();
  const transaction = db.transaction(LECTURES_STORE, "readwrite");
  const store = transaction.objectStore(LECTURES_STORE);
  const lecture = await requestResult<LocalLecture | undefined>(store.get(id));
  if (!lecture) throw new Error("Запись не найдена в хранилище");
  const updated = { ...lecture, chapters, summaryMd };
  store.put(updated);
  await transactionDone(transaction);
  return updated;
}
