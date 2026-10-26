import { useCallback, useEffect, useRef, useState } from "react";
import { Upload, type DetailedError } from "tus-js-client";
import { tokenStorage } from "../../api/client";
import { detailOf } from "./errors";

export const MAX_FILE_BYTES = 2 * 1024 ** 3;

const CHUNK_BYTES = 32 * 1024 ** 2;
const RETRY_DELAYS = [0, 1000, 3000, 5000, 10000, 20000];

export type UploadPhase = "idle" | "uploading" | "paused" | "offline" | "finishing" | "done" | "failed";

export type UploadState = {
  phase: UploadPhase;
  file: File | null;
  sent: number;
  total: number;
  error: string | null;
};

const idle: UploadState = { phase: "idle", file: null, sent: 0, total: 0, error: null };

const statusMessages: Record<number, string> = {
  401: "Сессия истекла. Войдите заново и выберите файл ещё раз",
  403: "Эту загрузку начали под другим аккаунтом",
  404: "Загрузка на сервере не найдена. Выберите файл заново",
  413: "Файл больше 2 ГБ",
};

function messageOf(error: Error | DetailedError) {
  const response = "originalResponse" in error ? error.originalResponse : null;
  if (!response) return "Связь с сервером прервалась. Загрузка продолжится с того же места";
  const status = response.getStatus();
  const detail = detailOf(parseBody(response.getBody()));
  if (typeof detail === "string") return detail;
  return statusMessages[status] ?? "Сервер не принял файл. Попробуйте ещё раз";
}

function parseBody(body: string) {
  try {
    return JSON.parse(body) as unknown;
  } catch {
    return undefined;
  }
}

async function launch(upload: Upload) {
  if (!upload.url) {
    const previous = await upload.findPreviousUploads();
    if (previous.length > 0) upload.resumeFromPreviousUpload(previous[0]);
  }
  upload.start();
}

export function useTusUpload(userId: string | undefined) {
  const [state, setState] = useState<UploadState>(idle);
  const current = useRef<Upload | null>(null);

  const update = useCallback((upload: Upload, next: (state: UploadState) => UploadState) => {
    setState((state) => (current.current === upload ? next(state) : state));
  }, []);

  const start = useCallback(
    (file: File, courseId: string | null) => {
      const metadata: Record<string, string> = { filename: file.name, filetype: file.type };
      if (courseId) metadata.course_id = courseId;
      const upload: Upload = new Upload(file, {
        endpoint: "/files/",
        chunkSize: CHUNK_BYTES,
        retryDelays: RETRY_DELAYS,
        removeFingerprintOnSuccess: true,
        metadata,
        fingerprint: async (source) =>
          ["lecturo", userId, courseId ?? "none", source.name, source.type, source.size, source.lastModified].join(":"),
        onBeforeRequest: (request) => {
          const token = tokenStorage.get();
          if (token) request.setHeader("Authorization", `Bearer ${token}`);
        },
        onProgress: (sent, total) =>
          update(upload, (state) => ({
            ...state,
            sent,
            total,
            phase: sent >= total ? "finishing" : state.phase === "paused" ? "paused" : "uploading",
          })),
        onSuccess: () => update(upload, (state) => ({ ...state, phase: "done", error: null })),
        onError: (error) =>
          update(upload, (state) => ({
            ...state,
            phase: navigator.onLine ? "failed" : "offline",
            error: navigator.onLine ? messageOf(error) : null,
          })),
      });
      current.current = upload;
      setState({ phase: "uploading", file, sent: 0, total: file.size, error: null });
      void launch(upload);
    },
    [update, userId],
  );

  const pause = useCallback(() => {
    const upload = current.current;
    if (!upload) return;
    void upload.abort();
    update(upload, (state) => ({ ...state, phase: "paused" }));
  }, [update]);

  const resume = useCallback(() => {
    const upload = current.current;
    if (!upload) return;
    update(upload, (state) => ({ ...state, phase: "uploading", error: null }));
    void launch(upload);
  }, [update]);

  const reset = useCallback(() => {
    const upload = current.current;
    current.current = null;
    if (upload) void upload.abort();
    setState(idle);
  }, []);

  useEffect(() => {
    if (state.phase !== "offline") return;
    window.addEventListener("online", resume);
    return () => window.removeEventListener("online", resume);
  }, [state.phase, resume]);

  const active = state.phase === "uploading" || state.phase === "paused" || state.phase === "offline" || state.phase === "finishing";

  useEffect(() => {
    if (!active) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [active]);

  useEffect(() => () => void current.current?.abort(), []);

  return { state, active, start, pause, resume, reset };
}
