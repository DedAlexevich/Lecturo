import { friendlyNotesError } from "./gpu";
import type { LocalChapter, LocalSegment } from "../storage";

export { NO_GPU_MESSAGE, supportsWebGPU } from "./gpu";

export type NotesProgress = { type: "loading"; value: number } | { type: "generating"; value: number };
export type Notes = { chapters: LocalChapter[]; summaryMd: string };

type Response = NotesProgress | ({ type: "done" } & Notes) | { type: "error"; message: string };

export function generateNotes(segments: LocalSegment[], onProgress: (progress: NotesProgress) => void, signal: AbortSignal): Promise<Notes> {
  signal.throwIfAborted();
  const worker = new Worker(new URL("./worker.ts", import.meta.url), { type: "module" });
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      worker.terminate();
      signal.removeEventListener("abort", onAbort);
    };
    const onAbort = () => {
      cleanup();
      reject(signal.reason);
    };
    signal.addEventListener("abort", onAbort, { once: true });
    worker.onmessage = (event: MessageEvent<Response>) => {
      const message = event.data;
      if (message.type === "loading" || message.type === "generating") {
        onProgress(message);
        return;
      }
      cleanup();
      if (message.type === "done") resolve({ chapters: message.chapters, summaryMd: message.summaryMd });
      else reject(new Error(friendlyNotesError(message.message)));
    };
    worker.onerror = (event) => {
      cleanup();
      reject(new Error(friendlyNotesError(event.message || "Не удалось запустить модель")));
    };
    worker.postMessage({ segments });
  });
}
