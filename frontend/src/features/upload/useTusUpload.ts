import { useCallback, useEffect, useRef, useState } from "react";
import { Upload, type DetailedError } from "tus-js-client";
import { tokenStorage } from "../../api/client";
import { detailOf } from "./errors";

export const MAX_FILE_BYTES = 2 * 1024 ** 3;

const CHUNK_BYTES = 32 * 1024 ** 2;
const RETRY_DELAYS = [0, 1000, 3000, 5000, 10000, 20000];

export type UploadPhase = "idle" | "extracting" | "uploading" | "paused" | "offline" | "finishing" | "done" | "failed";

export type UploadState = {
  phase: UploadPhase;
  file: File | null;
  sent: number;
  total: number;
  error: string | null;
  lectureId: string | null;
};

const idle: UploadState = { phase: "idle", file: null, sent: 0, total: 0, error: null, lectureId: null };

const statusMessages: Record<number, string> = {
  401: "Сессия истекла. Войдите заново и выберите файл ещё раз",
  403: "Эту загрузку начали под другим аккаунтом",
  404: "Загрузка на сервере не найдена. Выберите файл заново",
  422: "Не получилось прочитать запись. Выберите другой файл",
  413: "Файл больше 2 ГБ",
};

function responseOf(error: Error | DetailedError) {
  return "originalResponse" in error ? error.originalResponse : null;
}

function isRejected(error: Error | DetailedError) {
  const status = responseOf(error)?.getStatus() ?? 0;
  return status >= 400 && status < 500 && status !== 409 && status !== 423;
}

function messageOf(error: Error | DetailedError) {
  const response = responseOf(error);
  if (!response) return "Связь с сервером прервалась. Загрузка продолжится с того же места";
  const status = response.getStatus();
  const detail = detailOf(parseBody(response.getBody()));
  if (typeof detail === "string") return detail;
  return statusMessages[status] ?? "Сервер не принял файл. Попробуйте ещё раз";
}

function lectureIdOf(body: string) {
  const parsed = parseBody(body);
  if (typeof parsed !== "object" || parsed === null || !("lecture_id" in parsed)) return null;
  return typeof parsed.lecture_id === "string" ? parsed.lecture_id : null;
}

function parseBody(body: string) {
  try {
    return JSON.parse(body) as unknown;
  } catch {
    return undefined;
  }
}

async function audioFingerprint(file: File) {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function launch(upload: Upload, isCurrent: () => boolean) {
  if (!upload.url) {
    const previous = await upload.findPreviousUploads();
    if (!isCurrent()) return;
    if (previous.length > 0) upload.resumeFromPreviousUpload(previous[0]);
  }
  if (isCurrent()) upload.start();
}

export function useTusUpload(userId: string | undefined) {
  const [state, setState] = useState<UploadState>(idle);
  const current = useRef<Upload | null>(null);
  const extraction = useRef<AbortController | null>(null);
  const launchVersion = useRef(0);

  const update = useCallback((upload: Upload, next: (state: UploadState) => UploadState) => {
    setState((state) => (current.current === upload ? next(state) : state));
  }, []);

  const start = useCallback(
    async (original: File, courseId: string | null, audioOnly: boolean) => {
      let file = original;
      if (audioOnly) {
        const controller = new AbortController();
        extraction.current = controller;
        setState({ phase: "extracting", file, sent: 0, total: 100, error: null, lectureId: null });
        try {
          const { extractAudio } = await import("../../local/audio");
          const result = await extractAudio(file, {
            opus: true,
            signal: controller.signal,
            onProgress: (value) => setState((state) => extraction.current === controller ? { ...state, sent: value * 100 } : state),
          });
          if (!result.opus || result.opus.size === 0) throw new Error("Не удалось извлечь звук из файла");
          if (extraction.current !== controller) return;
          file = new File([result.opus], `${original.name.replace(/\.[^.]+$/, "")}.webm`, { type: result.opus.type, lastModified: original.lastModified });
          extraction.current = null;
        } catch (error) {
          if (extraction.current !== controller) return;
          extraction.current = null;
          setState({ ...idle, error: error instanceof Error ? error.message : "Не удалось извлечь звук из файла" });
          return;
        }
      }
      const metadata: Record<string, string> = { filename: file.name, filetype: file.type };
      if (audioOnly) metadata.audio_only = "true";
      if (courseId) metadata.course_id = courseId;
      const upload: Upload = new Upload(file, {
        endpoint: "/files/",
        chunkSize: CHUNK_BYTES,
        retryDelays: RETRY_DELAYS,
        removeFingerprintOnSuccess: true,
        metadata,
        fingerprint: async (source) =>
          ["lecturo", userId, courseId ?? "none", source.name, source.type, source.size, source.lastModified, ...(audioOnly ? [await audioFingerprint(source)] : [])].join(":"),
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
        onSuccess: ({ lastResponse }) =>
          update(upload, (state) => ({
            ...state,
            phase: "done",
            error: null,
            lectureId: lectureIdOf(lastResponse.getBody()),
          })),
        onError: (error) => {
          if (current.current !== upload) return;
          if (isRejected(error)) {
            current.current = null;
            setState({ ...idle, error: messageOf(error) });
            return;
          }
          update(upload, (state) => ({
            ...state,
            phase: navigator.onLine ? "failed" : "offline",
            error: navigator.onLine ? messageOf(error) : null,
          }));
        },
      });
      current.current = upload;
      setState({ phase: "uploading", file, sent: 0, total: file.size, error: null, lectureId: null });
      const version = ++launchVersion.current;
      void launch(upload, () => current.current === upload && launchVersion.current === version);
    },
    [update, userId],
  );

  const pause = useCallback(() => {
    const upload = current.current;
    if (!upload) return;
    launchVersion.current += 1;
    void upload.abort();
    update(upload, (state) => ({ ...state, phase: "paused" }));
  }, [update]);

  const resume = useCallback(() => {
    const upload = current.current;
    if (!upload) return;
    update(upload, (state) => ({ ...state, phase: "uploading", error: null }));
    const version = ++launchVersion.current;
    void launch(upload, () => current.current === upload && launchVersion.current === version);
  }, [update]);

  const reset = useCallback(() => {
    current.current = null;
    setState(idle);
  }, []);

  const cancel = useCallback(() => {
    const upload = current.current;
    extraction.current?.abort();
    extraction.current = null;
    current.current = null;
    setState(idle);
    upload?.abort(true).catch(() => upload.abort());
  }, []);

  useEffect(() => {
    if (state.phase !== "offline") return;
    window.addEventListener("online", resume);
    return () => window.removeEventListener("online", resume);
  }, [state.phase, resume]);

  const active = state.phase === "extracting" || state.phase === "uploading" || state.phase === "paused" || state.phase === "offline" || state.phase === "finishing";

  useEffect(() => {
    if (!active) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [active]);

  useEffect(() => () => { extraction.current?.abort(); void current.current?.abort(); }, []);

  return { state, active, start, pause, resume, reset, cancel };
}
