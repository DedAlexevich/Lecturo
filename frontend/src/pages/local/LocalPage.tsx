import { useEffect, useRef, useState } from "react";
import { extractAudio } from "../../local/audio";
import { disposeWhisper, transcribe } from "../../local/whisper";
import { disposeLlm } from "../../local/llm";
import type { Outline } from "../../local/llm";
import { saveLocalLecture, saveLocalOutline } from "../../local/storage";
import type { LocalLecture } from "../../local/storage";
import type { Segment, WhisperModel } from "../../local/whisper";
import { Chapters } from "../lecture/Chapters";
import { Transcript } from "../lecture/Transcript";
import { Markdown } from "../legal/markdown";
import { Button } from "../../ui/Button";
import { Progress } from "../../ui/Progress";
import { Tabs } from "../../ui/Tabs";
import { ExportButtons } from "./ExportButtons";
import { LocalLibrary } from "./LocalLibrary";
import { LocalOutline } from "./LocalOutline";
import { SaveToAccount } from "./SaveToAccount";
import "../lecture/lecture.css";
import "./local.css";

const models: { id: WhisperModel; label: string; size: string; description: string }[] = [
  { id: "tiny", label: "Tiny", size: "до 160 МБ", description: "Быстрее, но менее точно" },
  { id: "base", label: "Base", size: "до 300 МБ", description: "Баланс скорости и точности" },
  { id: "small", label: "Small", size: "до 1 ГБ", description: "Точнее, но медленнее" },
];

type Stage = "idle" | "extracting" | "loading" | "transcribing" | "done" | "error";

function outlineOf(lecture: LocalLecture): Outline | null {
  const summaryMd = lecture.summaryMd?.trim() ?? "";
  return lecture.chapters.length > 0 || summaryMd ? { chapters: lecture.chapters, summaryMd } : null;
}

export function LocalPage() {
  const [file, setFile] = useState<File | null>(null);
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
  const [libraryVersion, setLibraryVersion] = useState(0);
  const [outline, setOutline] = useState<Outline | null>(null);
  const [outlineSaveError, setOutlineSaveError] = useState(false);
  const [tab, setTab] = useState("summary");
  const player = useRef<HTMLMediaElement | null>(null);
  const controller = useRef<AbortController | null>(null);
  const busy = stage === "extracting" || stage === "loading" || stage === "transcribing";

  useEffect(() => {
    if (!file) return;
    const objectUrl = URL.createObjectURL(file);
    setUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [file]);

  useEffect(() => () => {
    controller.current?.abort();
    disposeWhisper();
    disposeLlm();
  }, []);

  async function start() {
    if (!file || busy) return;
    const abort = new AbortController();
    controller.current = abort;
    setError("");
    setSegments([]);
    setSaved(null);
    setSaveError(false);
    setOutline(null);
    setOutlineSaveError(false);
    disposeLlm();
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
      try {
        const lecture = await saveLocalLecture({
          title: file.name.replace(/\.[^.]+$/, "") || file.name,
          durationSec: audio.duration,
          language,
          model,
          segments: result,
        });
        setSaved(lecture);
        setLibraryVersion((value) => value + 1);
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

  function cancel() {
    controller.current?.abort();
    controller.current = null;
    disposeWhisper();
    setStage("idle");
    setProgress(undefined);
  }

  function selectFile(next: File | null) {
    setFile(next);
    setStage("idle");
    setSegments([]);
    setSaved(null);
    setSaveError(false);
    setOutline(null);
    setOutlineSaveError(false);
    setError("");
    setCurrentTime(0);
  }

  function openSaved(lecture: LocalLecture) {
    controller.current?.abort();
    setFile(null);
    setUrl("");
    setSaved(lecture);
    setSaveError(false);
    setSegments(lecture.segments);
    setOutline(outlineOf(lecture));
    setOutlineSaveError(false);
    setTab("summary");
    setError("");
    setCurrentTime(0);
    setStage("done");
  }

  function removed(id: string) {
    if (saved?.id !== id) return;
    setSaved(null);
    setSegments([]);
    setOutline(null);
    setStage("idle");
  }

  async function outlineReady(next: Outline) {
    setOutline(next);
    setTab("summary");
    setOutlineSaveError(false);
    if (!saved) return;
    try {
      const updated = await saveLocalOutline(saved.id, next);
      if (updated) setSaved(updated);
      setLibraryVersion((value) => value + 1);
    } catch {
      setOutlineSaveError(true);
    }
  }

  const selectedModel = models.find((item) => item.id === model)!;
  const hasPlayer = Boolean(file && url);
  const seek = (time: number) => {
    if (player.current) player.current.currentTime = time;
  };
  const transcript = <Transcript segments={segments} currentTime={currentTime} onSelect={seek} />;
  const stageLabel = stage === "extracting" ? "Извлечение звука" : stage === "loading" ? "Загрузка модели" : "Распознавание речи";

  return (
    <div className="local-page">
      <header className="local-page__header">
        <h1>Обработка на устройстве</h1>
        <p>Расшифруйте запись в браузере. Файл остаётся на устройстве. Текст можно сохранить в аккаунт.</p>
      </header>
      <div className="local-page__layout">
        <section className="local-setup" aria-labelledby="local-setup-title">
          <h2 id="local-setup-title">Новая запись</h2>
          <label className="local-field">
            <span>Аудио или видео</span>
            <input type="file" accept="audio/*,video/*" disabled={busy} onChange={(event) => selectFile(event.target.files?.[0] ?? null)} />
          </label>
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
            {busy && <Button variant="secondary" onClick={cancel}>Отменить</Button>}
          </div>
          {busy && <div className="local-status" aria-live="polite"><Progress label={stageLabel} value={progress} /></div>}
          {stage === "error" && <p className="local-error" role="alert">Не удалось обработать запись: {error}</p>}
        </section>
        <section className="local-result" aria-labelledby="local-result-title">
          <div className="local-result__head"><h2 id="local-result-title">Расшифровка</h2><p>{file ? file.name : saved ? saved.title : "Выберите файл, чтобы начать"}</p></div>
          {file && url && (file.type.startsWith("video/") ? (
            <video ref={(element) => { player.current = element; }} className="local-player" controls src={url} onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)} />
          ) : (
            <audio ref={(element) => { player.current = element; }} className="local-player" controls src={url} onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)} />
          ))}
          {stage === "done" && segments.length > 0 ? (outline ? (
            <Tabs
              label="Материалы лекции"
              value={tab}
              onChange={setTab}
              items={[
                {
                  id: "summary",
                  label: "Конспект",
                  panel: outline.summaryMd ? (
                    <div className="lecture__scroll summary"><Markdown source={outline.summaryMd} /></div>
                  ) : <p className="lecture__panel-note">Конспект не получился. Попробуйте составить его заново.</p>,
                },
                {
                  id: "chapters",
                  label: "Главы",
                  panel: outline.chapters.length > 0 ? (
                    <div className="lecture__scroll">
                      <Chapters chapters={outline.chapters} currentTime={hasPlayer ? currentTime : null} onSelect={hasPlayer ? seek : undefined} />
                    </div>
                  ) : <p className="lecture__panel-note">Лекция слишком короткая, чтобы делить её на главы.</p>,
                },
                { id: "transcript", label: "Расшифровка", panel: transcript },
              ]}
            />
          ) : transcript) : <p className="local-result__empty">{stage === "done" ? "Речь в записи не найдена." : "Здесь появится текст с отметками времени."}</p>}
          {stage === "done" && segments.length > 0 && (
            <LocalOutline
              key={`outline-${saved?.id ?? file?.name ?? ""}`}
              title={saved?.title ?? file?.name ?? ""}
              segments={segments}
              hasOutline={outline !== null}
              onDone={outlineReady}
            />
          )}
          {outlineSaveError && <p className="local-error" role="alert">Не удалось сохранить конспект в браузере. Он доступен только до закрытия страницы.</p>}
          {stage === "done" && saved && <ExportButtons lecture={saved} />}
          {stage === "done" && saved && <SaveToAccount key={saved.id} lecture={saved} />}
          {stage === "done" && saved && <p className="local-note local-result__note">Результат сохранён в этом браузере и останется после перезагрузки страницы.</p>}
          {stage === "done" && saveError && <p className="local-error" role="alert">Не удалось сохранить результат в браузере. Он доступен только до закрытия страницы.</p>}
        </section>
      </div>
      <LocalLibrary version={libraryVersion} activeId={saved?.id} onOpen={openSaved} onRemoved={removed} />
    </div>
  );
}
