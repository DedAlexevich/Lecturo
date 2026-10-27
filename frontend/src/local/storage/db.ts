export const DB_NAME = "lecturo-local";
export const DB_VERSION = 2;
export const LECTURES_STORE = "lectures";
export const MEDIA_STORE = "media";

function migrate(db: IDBDatabase, oldVersion: number) {
  if (oldVersion < 1) {
    const store = db.createObjectStore(LECTURES_STORE, { keyPath: "id" });
    store.createIndex("createdAt", "createdAt");
  }
  if (oldVersion < 2) {
    db.createObjectStore(MEDIA_STORE, { keyPath: "id" });
  }
}

let opened: Promise<IDBDatabase> | null = null;

export function openDb(): Promise<IDBDatabase> {
  if (opened) return opened;
  const attempt = new Promise<IDBDatabase>((resolve, reject) => {
    if (typeof indexedDB === "undefined") {
      reject(new Error("Хранилище браузера недоступно"));
      return;
    }
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = (event) => migrate(request.result, event.oldVersion);
    request.onsuccess = () => {
      const db = request.result;
      db.onversionchange = () => {
        db.close();
        opened = null;
      };
      db.onclose = () => {
        opened = null;
      };
      resolve(db);
    };
    request.onerror = () => reject(request.error ?? new Error("Не удалось открыть хранилище"));
    request.onblocked = () => reject(new Error("Хранилище занято другой вкладкой"));
  });
  opened = attempt;
  attempt.catch(() => {
    if (opened === attempt) opened = null;
  });
  return attempt;
}

export function requestResult<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("Ошибка хранилища"));
  });
}

export function transactionDone(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error ?? new Error("Ошибка хранилища"));
    transaction.onabort = () => reject(transaction.error ?? new Error("Запись отменена"));
  });
}
