import { LECTURES_STORE, MEDIA_STORE, openDb, requestResult, transactionDone } from "./db";

interface StoredMedia {
  id: string;
  name: string;
  type: string;
  blob: Blob;
}

export interface LocalMedia {
  name: string;
  type: string;
  blob: Blob;
}

async function requestPersistence() {
  const storage = navigator.storage;
  if (!storage?.persist || (await storage.persisted())) return;
  await storage.persist();
}

export async function saveLocalMedia(id: string, file: File): Promise<void> {
  await requestPersistence().catch(() => undefined);
  const db = await openDb();
  const transaction = db.transaction([LECTURES_STORE, MEDIA_STORE], "readwrite");
  const lecture = transaction.objectStore(LECTURES_STORE).getKey(id);
  lecture.onsuccess = () => {
    if (lecture.result === undefined) return;
    const record: StoredMedia = { id, name: file.name, type: file.type, blob: file };
    transaction.objectStore(MEDIA_STORE).put(record);
  };
  await transactionDone(transaction);
}

export async function getLocalMedia(id: string): Promise<LocalMedia | null> {
  const db = await openDb();
  const record = await requestResult<StoredMedia | undefined>(db.transaction(MEDIA_STORE).objectStore(MEDIA_STORE).get(id));
  if (!record) return null;
  return { name: record.name, type: record.type || record.blob.type, blob: record.blob };
}
