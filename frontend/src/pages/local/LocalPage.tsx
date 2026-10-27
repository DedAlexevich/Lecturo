import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router";
import { useToken } from "../../app/session";
import { extractAudio } from "../../local/audio";
import { pickedFileOf } from "../../local/pickedFiles";
import { disposeWhisper, transcribe } from "../../local/whisper";
import { generateNotes, markWebGPUUnsupported, NO_GPU_MESSAGE, NoGpuError, supportsWebGPU } from "../../local/llm";
import { getLocalMedia, saveLocalLecture, saveLocalMedia, updateLocalNotes } from "../../local/storage";
import type { LocalLecture, LocalMedia } from "../../local/storage";
import type { Segment, WhisperModel } from "../../local/whisper";
import { SummaryMarkdown } from "../lecture/SummaryMarkdown";
import { Chapters } from "../lecture/Chapters";
import { Transcript } from "../lecture/Transcript";
import { fetchLecture, lectureQueryKey } from "../lecture/useLecture";
import { Button } from "../../ui/Button";
import { Progress } from "../../ui/Progress";
import { Spinner } from "../../ui/Spinner";
import { ExportButtons } from "./ExportButtons";
import { LocalLibrary } from "./LocalLibrary";
import { MissingMedia } from "./MissingMedia";
import { QueueRelease } from "./QueueRelease";
import { SaveToAccount } from "./SaveToAccount";
import "../lecture/lecture.css";
import "./local.css";

const models: { id: WhisperModel; label: string; size: string; description: string }[] = [
  { id: "tiny", label: "Tiny", size: "до 160 МБ", description: "Быстрее, но менее точно" },
  { id: "base", label: "Base", size: "до 300 МБ", description: "Баланс скорости и точности" },
  { id: "small", label: "Small", size: "до 1 ГБ", description: "Точнее, но медленнее" },
];

type Stage = "idle" | "extracting" | "loading" | "transcribing" | "done" | "error";
type MediaState = "none" | "loading" | "ready" | "missing";

export function LocalPage() {
  const [searchParams] = useSearchParams();
  const lectureId = searchParams.get("lecture");
  return <LocalProcessing key={lectureId ?? ""} lectureId={lectureId} />;
}

function useQueuedLecture(lectureId: string | null, token: string | null) {
  return useQuery({
    queryKey: lectureQueryKey(lectureId ?? ""),
    enabled: lectureId !== null && token !== null,
    queryFn: () => fetchLecture(lectureId ?? ""),
    retry: false,
  });
}

function LocalProcessing({ lectureId }: { lectureId: string | null }) {
  const [queuedFile] = useState(() => (lectureId ? pickedFileOf(lectureId) : null));
  const [file, setFile] = useState<File | null>(queuedFile);
  const [usingQueued, setUsingQueued] = useState(queuedFile !== null);
  const token = useToken();
  const lecture = useQueuedLecture(lectureId, token);
  const [released, setReleased] = useState(false);
  const [model, setModel] = useState<WhisperModel>("tiny");
  const [language, setLanguage] = useState("ru");
  const [stage, setStage] = useState<Stage>("idle");
  const [progress, setProgress] = useState<number>();
  const [segments, setSegments] = useState<Segment[]>([]);
  const [error, setError] = useState("");
  const [url, setUrl] = useState("");
  const [currentTime, setCurrentTime] = useState(0);
  const [saved, setSaved] = useState<LocalLecture | null>(null);
  const [saveError, setSaveError] = useState(false);
  const [webgpu, setWebgpu] = useState<boolean | null>(null);
  const [notesProgress, setNotesProgress] = useState<{ type: "loading" | "generating" | "saving"; value: number } | null>(null);
  const [notesError, setNotesError] = useState("");
  const [libraryVersion, setLibraryVersion] = useState(0);
  const [savedMedia, setSavedMedia] = useState<LocalMedia | null>(null);
  const [mediaState, setMediaState] = useState<MediaState>("none");
  const [mediaSaveError, setMediaSaveError] = useState(false);
  const openedId = useRef<string | null>(null);
  const player = useRef<HTMLMediaElement | null>(null);
  const controller = useRef<AbortController | null>(null);
  const savingNotes = useRef(false);
  const transcriptionBusy = stage === "extracting" || stage === "loading" || stage === "transcribing";
  const busy = transcriptionBusy || notesProgress !== null;

  useEffect(() => {
    let active = true;
    void supportsWebGPU().then((supported) => { if (active) setWebgpu(supported); });
    return () => { active = false; };
  }, []);

  const media = file ?? savedMedia?.blob ?? null;
  const mediaType = file ? file.type : savedMedia?.type ?? "";

  useEffect(() => {
    if (!media) {
      setUrl("");
      return;
    }
    const objectUrl = URL.createObjectURL(media);
    setUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [media]);

  function resetMedia(id: string | null) {
    openedId.current = id;
    setSavedMedia(null);
    setMediaState("none");
    setMediaSaveError(false);
  }

  async function storeMedia(id: string, source: File) {
    try {
      await saveLocalMedia(id, source);
    } catch {
      if (openedId.current === id) setMediaSaveError(true);
    }
  }

  useEffect(() => () => {
    controller.current?.abort();
    disposeWhisper();
  }, []);

  async function start() {
    if (!file || busy) return;
    const abort = new AbortController();
    controller.current = abort;
    setError("");
    setSegments([]);
    setSaved(null);
    setSaveError(false);
    resetMedia(null);
    setStage("extracting");
    setProgress(undefined);
    try {
      const audio = await extractAudio(file, { signal: abort.signal, onProgress: (value) => setProgress(value * 100) });
      setStage("loading");
      setProgress(undefined);
      const result = await transcribe(audio.pcm, model, ({ stage: next, value }) => {
        setStage(next);
        setProgress(next === "loading" ? undefined : value * 100);
      }, { signal: abort.signal, language });
      setSegments(result);
      setStage("done");
      if (lectureId !== null && token !== null) void lecture.refetch();
      try {
        const local = await saveLocalLecture({
          title: (usingQueued ? lecture.data?.title : undefined) ?? (file.name.replace(/\.[^.]+$/, "") || file.name),
          durationSec: audio.duration,
          language,
          model,
          segments: result,
        });
        setSaved(local);
        openedId.current = local.id;
        setLibraryVersion((value) => value + 1);
        await storeMedia(local.id, file);
      } catch {
        setSaveError(true);
      }
    } catch (reason) {
      if (abort.signal.aborted) return;
      setError(reason instanceof Error ? reason.message : "Не удалось обработать файл");
      setStage("error");
    } finally {
      if (controller.current === abort) controller.current = null;
    }
  }

  async function makeNotes() {
    if (!saved || busy) return;
    const abort = new AbortController();
    controller.current = abort;
    setNotesError("");
    setNotesProgress({ type: "loading", value: 0 });
    try {
      const result = await generateNotes(saved.segments, setNotesProgress, abort.signal);
      abort.signal.throwIfAborted();
      savingNotes.current = true;
      setNotesProgress({ type: "saving", value: 0 });
      const updated = await updateLocalNotes(saved.id, result.chapters, result.summaryMd);
      if (abort.signal.aborted) return;
      setSaved(updated);
      setLibraryVersion((value) => value + 1);
    } catch (reason) {
      if (!abort.signal.aborted) {
        if (reason instanceof NoGpuError) {
          markWebGPUUnsupported();
          setWebgpu(false);
        } else {
          setNotesError(reason instanceof Error ? reason.message : "Не удалось построить конспект");
        }
      }
    } finally {
      savingNotes.current = false;
      if (controller.current === abort) controller.current = null;
      if (!abort.signal.aborted) setNotesProgress(null);
    }
  }

  function cancel() {
    if (savingNotes.current) return;
    controller.current?.abort();
    controller.current = null;
    disposeWhisper();
    setNotesProgress(null);
    if (notesProgress) return;
    setStage("idle");
    setProgress(undefined);
  }

  function selectFile(next: File | null) {
    resetMedia(null);
    setFile(next);
    setStage("idle");
    setSegments([]);
    setSaved(null);
    setSaveError(false);
    setNotesError("");
    setError("");
    setCurrentTime(0);
  }

  function openSaved(lecture: LocalLecture) {
    controller.current?.abort();
    setFile(null);
    resetMedia(lecture.id);
    setMediaState("loading");
    setSaved(lecture);
    setSaveError(false);
    setNotesError("");
    setSegments(lecture.segments);
    setError("");
    setCurrentTime(0);
    setStage("done");
    getLocalMedia(lecture.id).then(
      (found) => {
        if (openedId.current !== lecture.id) return;
        setSavedMedia(found);
        setMediaState(found ? "ready" : "missing");
      },
      () => {
        if (openedId.current === lecture.id) setMediaState("missing");
      },
    );
  }

  function relinkMedia(next: File) {
    if (!saved) return;
    setSavedMedia({ name: next.name, type: next.type, blob: next });
    setMediaState("ready");
    setMediaSaveError(false);
    void storeMedia(saved.id, next);
  }

  function removed(id: string) {
    if (saved?.id !== id) return;
    resetMedia(null);
    setSaved(null);
    setSegments([]);
    setStage("idle");
  }

  function pickAnother() {
    setUsingQueued(false);
    selectFile(null);
  }

  const queued = lecture.data;
  const waitingLecture = queued?.status === "waiting_quota" ? queued : undefined;
  const fromLink = waitingLecture?.source_type === "link";
  const lostFile = waitingLecture?.source_type === "upload" && queuedFile === null && file === null;
  const selectedModel = models.find((item) => item.id === model)!;
  const stageLabel = stage === "extracting" ? "Извлечение звука" : stage === "loading" ? "Загрузка модели" : "Распознавание речи";

  return (
    <div className="local-page">
      <header className="local-page__header">
        <h1>Обработка на устройстве</h1>
        <p>Расшифруйте запись в браузере. Файл остаётся на устройстве. Текст можно сохранить в аккаунт.</p>
      </header>
      <div className="local-page__layout">
        <section className="local-setup" aria-labelledby="local-setup-title">
          <h2 id="local-setup-title">{waitingLecture || usingQueued ? "Лекция из очереди" : "Новая запись"}</h2>
          {lectureId && !usingQueued && lecture.isLoading && (
            <p className="local-source__status"><Spinner size="sm" label="Загружаем лекцию" />Загружаем лекцию</p>
          )}
          {fromLink && (
            <div className="local-source local-source--notice" role="status">
              <p className="local-source__title">«{waitingLecture.title}» добавлена по ссылке</p>
              <p>На устройстве обрабатывается только файл с записью. Если он у вас есть, выберите его ниже. Иначе лекция дождётся лимита и обработается на сервере.</p>
            </div>
          )}
          {lostFile && !usingQueued && (
            <div className="local-source local-source--notice" role="status">
              <p className="local-source__title">«{waitingLecture.title}»</p>
              <p>Выберите файл этой лекции: в этой вкладке браузера его уже нет.</p>
            </div>
          )}
          {lectureId && lecture.isError && !usingQueued && !released && (
            <p className="local-note">Не удалось найти лекцию из очереди. Выберите файл с записью.</p>
          )}
          {usingQueued && file ? (
            <div className="local-source">
              {queued && <p className="local-source__title">«{queued.title}»</p>}
              <p className="local-source__file">{file.name}</p>
              <Button variant="ghost" size="sm" className="local-source__change" disabled={busy} onClick={pickAnother}>
                Выбрать другой файл
              </Button>
            </div>
          ) : (
            <label className="local-field">
              <span>Аудио или видео</span>
              <input type="file" accept="audio/*,video/*" disabled={busy} onChange={(event) => selectFile(event.target.files?.[0] ?? null)} />
            </label>
          )}
          <label className="local-field">
            <span>Модель распознавания</span>
            <select value={model} disabled={busy} onChange={(event) => setModel(event.target.value as WhisperModel)}>
              {models.map((item) => <option key={item.id} value={item.id}>{item.label} — {item.description}</option>)}
            </select>
          </label>
          <label className="local-field">
            <span>Язык записи</span>
            <select value={language} disabled={busy} onChange={(event) => setLanguage(event.target.value)}>
              <option value="ru">Русский</option>
              <option value="en">Английский</option>
            </select>
          </label>
          <p className="local-note">{selectedModel.label}: {selectedModel.size}. При первом запуске модель загружается из интернета и сохраняется в браузере. Для повторной обработки интернет не нужен, пока данные браузера не удалены.</p>
          <div className="local-actions">
            <Button disabled={!file || busy} onClick={() => void start()}>Распознать</Button>
            {transcriptionBusy && <Button variant="secondary" onClick={cancel}>Отменить</Button>}
          </div>
          {transcriptionBusy && <div className="local-status" aria-live="polite"><Progress label={stageLabel} value={progress} /></div>}
          {stage === "error" && <p className="local-error" role="alert">Не удалось обработать запись: {error}</p>}
        </section>
        <section className="local-result" aria-labelledby="local-result-title">
          <div className="local-result__head"><h2 id="local-result-title">Расшифровка</h2><p>{file ? file.name : saved ? saved.title : "Выберите файл, чтобы начать"}</p></div>
          {media && url && (mediaType.startsWith("video/") ? (
            <video ref={(element) => { player.current = element; }} className="local-player" controls src={url} onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)} />
          ) : (
            <audio ref={(element) => { player.current = element; }} className="local-player" controls src={url} onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)} />
          ))}
          {!file && saved && mediaState === "loading" && <p className="local-media-loading"><Spinner size="sm" label="Загружаем запись" /></p>}
          {!file && saved && mediaState === "missing" && <MissingMedia disabled={busy} onPick={relinkMedia} />}
          {stage === "done" && segments.length > 0 ? (
            <Transcript segments={segments} chapters={saved?.chapters} currentTime={currentTime} onSelect={(time) => { if (player.current) player.current.currentTime = time; }} />
          ) : <p className="local-result__empty">{stage === "done" ? "Речь в записи не найдена." : "Здесь появится текст с отметками времени."}</p>}
          {stage === "done" && saved && segments.length > 0 && webgpu === true && <div className="local-actions">
            <Button disabled={busy} onClick={() => void makeNotes()}>{saved.summaryMd ? "Обновить конспект и главы" : "Создать конспект и главы"}</Button>
            {notesProgress && notesProgress.type !== "saving" && <Button variant="secondary" onClick={cancel}>Отменить</Button>}
          </div>}
          {stage === "done" && saved && segments.length > 0 && webgpu === true && !saved.summaryMd && <p className="local-note">При первом запуске модель конспекта загружается из интернета. Для работы ей требуется около 2 ГБ видеопамяти. Текст обрабатывается на устройстве.</p>}
          {stage === "done" && saved && segments.length > 0 && webgpu === false && !busy && (
            <div className="local-source local-source--notice" role="status">
              <p>{NO_GPU_MESSAGE}</p>
              <SaveToAccount key={saved.id} lecture={saved} />
            </div>
          )}
          {notesProgress && <Progress label={notesProgress.type === "loading" ? "Загрузка модели конспекта" : notesProgress.type === "saving" ? "Сохранение конспекта" : "Создание конспекта"} value={notesProgress.type === "saving" ? undefined : notesProgress.value * 100} />}
          {notesError && <p className="local-error" role="alert">Не удалось создать конспект: {notesError}</p>}
          {saved?.summaryMd && <section><h2>Конспект</h2><div className="summary"><SummaryMarkdown source={saved.summaryMd} /></div></section>}
          {saved && saved.chapters.length > 0 && <section><h2>Главы</h2><Chapters chapters={saved.chapters} currentTime={currentTime} onSelect={(time) => { if (player.current) player.current.currentTime = time; }} /></section>}
          {stage === "done" && saved && <ExportButtons lecture={saved} />}
          {stage === "done" && saved && !busy && (webgpu === true || segments.length === 0) && <SaveToAccount key={saved.id} lecture={saved} />}
          {stage === "done" && saved && <p className="local-note local-result__note">Результат сохранён в этом браузере и останется после перезагрузки страницы.</p>}
          {stage === "done" && file && !released && !lecture.isFetching && !lecture.isError && queued?.status === "waiting_quota" && (
            <QueueRelease lecture={queued} onReleased={() => setReleased(true)} />
          )}
          {stage === "done" && saved && mediaSaveError && <p className="local-note" role="status">Запись не поместилась в хранилище браузера. После перезагрузки страницы её нужно будет выбрать заново.</p>}
          {stage === "done" && saveError && <p className="local-error" role="alert">Не удалось сохранить результат в браузере. Он доступен только до закрытия страницы.</p>}
        </section>
      </div>
      <LocalLibrary disabled={busy} version={libraryVersion} activeId={saved?.id} onOpen={openSaved} onRemoved={removed} />
    </div>
  );
}
