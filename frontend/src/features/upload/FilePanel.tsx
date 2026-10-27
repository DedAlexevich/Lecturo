import { useId, useState, type DragEvent, type ReactNode } from "react";
import { Button } from "../../ui/Button";
import { Progress } from "../../ui/Progress";
import { formatBytes } from "./format";
import { MAX_FILE_BYTES, type UploadState } from "./useTusUpload";

type FilePanelProps = {
  state: UploadState;
  file: File | null;
  onPick: (file: File) => void;
  ready: boolean;
  courseField: ReactNode;
  onStart: (file: File, audioOnly: boolean) => void;
  onPause: () => void;
  onResume: () => void;
  onCancel: () => void;
  onClose: () => void;
};

function problemOf(file: File) {
  if (file.size === 0) return "Файл пустой";
  if (file.size > MAX_FILE_BYTES) return `Файл весит ${formatBytes(file.size)}, а можно не больше 2 ГБ`;
  if (file.type && !file.type.startsWith("audio/") && !file.type.startsWith("video/")) return "Нужна видео- или аудиозапись";
  return null;
}

const statusText: Partial<Record<UploadState["phase"], string>> = {
  paused: "На паузе. Можно продолжить с того же места",
  offline: "Нет сети. Загрузка продолжится, когда связь вернётся",
  finishing: "Файл загружен, проверяем запись",
};

function UploadProgress({ state, onPause, onResume, onCancel, onClose }: Omit<FilePanelProps, "ready" | "courseField" | "onStart" | "file" | "onPick">) {
  const percent = state.total > 0 ? (state.sent / state.total) * 100 : 0;
  const finishing = state.phase === "finishing";
  const extracting = state.phase === "extracting";
  const message = state.phase === "failed" ? state.error : statusText[state.phase];

  return (
    <div className="add-lecture__upload">
      <p className="add-lecture__file-name">{state.file?.name}</p>
      <Progress
        label={extracting ? "Извлекаем звук" : finishing ? "Проверяем файл" : `${formatBytes(state.sent)} из ${formatBytes(state.total)}`}
        value={finishing ? undefined : percent}
      />
      {message && (
        <p className={state.phase === "failed" ? "add-lecture__error" : "add-lecture__note"} role={state.phase === "failed" ? "alert" : "status"}>
          {message}
        </p>
      )}
      {!finishing && <p className="add-lecture__note">Окно можно закрыть, загрузка продолжится. Вкладку не закрывайте.</p>}
      <div className="dialog__actions">
        <Button variant="ghost" onClick={onCancel} disabled={finishing}>
          Отменить загрузку
        </Button>
        <Button variant="secondary" onClick={onClose}>
          Свернуть
        </Button>
        {state.phase === "uploading" && <Button onClick={onPause}>Пауза</Button>}
        {state.phase === "paused" && <Button onClick={onResume}>Продолжить</Button>}
        {state.phase === "failed" && <Button onClick={onResume}>Повторить</Button>}
        {state.phase === "offline" && <Button onClick={onResume}>Повторить сейчас</Button>}
      </div>
    </div>
  );
}

export function FilePanel(props: FilePanelProps) {
  const { state, file, ready, courseField, onStart, onPick, onClose } = props;
  const [dragging, setDragging] = useState(false);
  const [audioOnly, setAudioOnly] = useState(false);
  const hintId = useId();
  const problem = file ? problemOf(file) : null;
  const message = file ? problem : state.error;

  if (state.phase !== "idle" && state.phase !== "done") return <UploadProgress {...props} />;

  const pick = (picked: File | undefined) => {
    if (picked) onPick(picked);
  };

  const onDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setDragging(false);
    pick(event.dataTransfer.files[0]);
  };

  return (
    <form
      className="add-lecture__form"
      onSubmit={(event) => {
        event.preventDefault();
        if (file && !problem) onStart(file, audioOnly);
      }}
    >
      <label
        className={dragging ? "add-lecture__drop add-lecture__drop--active" : "add-lecture__drop"}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <input
          type="file"
          accept="video/*,audio/*"
          className="add-lecture__input"
          aria-describedby={hintId}
          aria-invalid={problem ? true : undefined}
          onChange={(event) => pick(event.target.files?.[0])}
        />
        {file ? (
          <>
            <span className="add-lecture__drop-title">{file.name}</span>
            <span className="add-lecture__drop-hint">{formatBytes(file.size)} · выбрать другой</span>
          </>
        ) : (
          <>
            <span className="add-lecture__drop-title">Выберите запись</span>
            <span className="add-lecture__drop-hint">или перетащите файл сюда</span>
          </>
        )}
      </label>
      <p className="add-lecture__note" id={hintId}>
        Видео или аудио до 2 ГБ и до 4 часов. Если связь оборвётся, загрузка продолжится с того же места.
      </p>
      {message && (
        <p className="add-lecture__error" role="alert">
          {message}
        </p>
      )}
      <label className="add-lecture__audio-only">
        <input type="checkbox" checked={audioOnly} onChange={(event) => setAudioOnly(event.target.checked)} />
        <span>Загрузить только звук</span>
      </label>
      {courseField}
      <div className="dialog__actions">
        <Button variant="ghost" onClick={onClose}>
          Отмена
        </Button>
        <Button type="submit" disabled={!file || problem !== null || !ready}>
          Загрузить
        </Button>
      </div>
    </form>
  );
}
