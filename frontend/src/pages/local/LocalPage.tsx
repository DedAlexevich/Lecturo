import { useEffect, useRef, useState } from "react";
import { extractAudio } from "../../local/audio";
import { disposeWhisper, transcribe } from "../../local/whisper";
import type { Segment, WhisperModel } from "../../local/whisper";
import { Transcript } from "../lecture/Transcript";
import { Button } from "../../ui/Button";
import { Progress } from "../../ui/Progress";
import "../lecture/lecture.css";
import "./local.css";

const models: { id: WhisperModel; label: string; size: string; description: string }[] = [
  { id: "tiny", label: "Tiny", size: "до 160 МБ", description: "Быстрее, но менее точно" },
  { id: "base", label: "Base", size: "до 300 МБ", description: "Баланс скорости и точности" },
  { id: "small", label: "Small", size: "до 1 ГБ", description: "Точнее, но медленнее" },
];

type Stage = "idle" | "extracting" | "loading" | "transcribing" | "done" | "error";

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
  }, []);

  async function start() {
    if (!file || busy) return;
    const abort = new AbortController();
    controller.current = abort;
    setError("");
    setSegments([]);
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
    setError("");
    setCurrentTime(0);
  }

  const selectedModel = models.find((item) => item.id === model)!;
  const stageLabel = stage === "extracting" ? "Извлечение звука" : stage === "loading" ? "Загрузка модели" : "Распознавание речи";

  return (
    <div className="local-page">
      <header className="local-page__header">
        <h1>Обработка на устройстве</h1>
        <p>Расшифруйте запись в браузере. Файл и текст не отправляются на сервер.</p>
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
          <div className="local-result__head"><h2 id="local-result-title">Расшифровка</h2><p>{file ? file.name : "Выберите файл, чтобы начать"}</p></div>
          {file && url && (file.type.startsWith("video/") ? (
            <video ref={(element) => { player.current = element; }} className="local-player" controls src={url} onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)} />
          ) : (
            <audio ref={(element) => { player.current = element; }} className="local-player" controls src={url} onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)} />
          ))}
          {stage === "done" && segments.length > 0 ? (
            <Transcript segments={segments} currentTime={currentTime} onSelect={(time) => { if (player.current) player.current.currentTime = time; }} />
          ) : <p className="local-result__empty">{stage === "done" ? "Речь в записи не найдена." : "Здесь появится текст с отметками времени."}</p>}
          {stage === "done" && <p className="local-note local-result__note">Результат доступен только на этой странице. Сохраните нужный текст до её закрытия.</p>}
        </section>
      </div>
    </div>
  );
}
