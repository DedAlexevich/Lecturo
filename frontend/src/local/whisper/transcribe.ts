import { detectDevice } from "./device";
import type {
  ProgressHandler,
  Segment,
  TranscribeOptions,
  WhisperModel,
  WorkerRequest,
  WorkerResponse,
} from "./types";

let worker: Worker | null = null;
let nextId = 1;
const pending = new Map<number, (error: Error) => void>();

function getWorker(): Worker {
  worker ??= new Worker(new URL("./worker.ts", import.meta.url), { type: "module" });
  return worker;
}

export function disposeWhisper() {
  worker?.terminate();
  worker = null;
  const rejections = [...pending.values()];
  pending.clear();
  for (const reject of rejections) reject(new DOMException("Aborted", "AbortError"));
}

export async function transcribe(
  audio: Float32Array,
  model: WhisperModel,
  onProgress?: ProgressHandler,
  options: TranscribeOptions = {},
): Promise<Segment[]> {
  const { signal, language } = options;
  signal?.throwIfAborted();
  const device = await detectDevice();
  signal?.throwIfAborted();

  const target = getWorker();
  const id = nextId++;

  return new Promise<Segment[]>((resolve, reject) => {
    pending.set(id, reject);
    const cleanup = () => {
      pending.delete(id);
      target.removeEventListener("message", onMessage);
      target.removeEventListener("error", onError);
      signal?.removeEventListener("abort", onAbort);
    };
    const onMessage = (event: MessageEvent<WorkerResponse>) => {
      const message = event.data;
      if (message.id !== id) return;
      if (message.type === "progress") {
        onProgress?.(message.progress);
        return;
      }
      cleanup();
      if (message.type === "done") resolve(message.segments);
      else reject(new Error(message.message));
    };
    const onError = (event: ErrorEvent) => {
      cleanup();
      disposeWhisper();
      reject(new Error(event.message || "Не удалось запустить распознавание"));
    };
    const onAbort = () => {
      cleanup();
      reject(signal?.reason ?? new DOMException("Aborted", "AbortError"));
    };

    target.addEventListener("message", onMessage);
    target.addEventListener("error", onError);
    signal?.addEventListener("abort", onAbort);

    const request: WorkerRequest = { id, audio, model, device, language };
    target.postMessage(request);
  });
}
