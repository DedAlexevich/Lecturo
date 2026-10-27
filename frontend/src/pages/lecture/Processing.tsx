import type { components } from "../../api/schema";
import { detailOf } from "../../features/upload/errors";
import { ApiError } from "../../app/queryClient";
import { Button } from "../../ui/Button";
import { Progress } from "../../ui/Progress";

type LectureStatus = components["schemas"]["LectureStatus"];
type Step = components["schemas"]["StepOut"];

const stepOrder: Step["step"][] = ["download", "audio", "video", "transcribe", "summarize", "embed"];

const stepLabels: Record<Step["step"], string> = {
  download: "Скачивание",
  audio: "Извлечение звука",
  video: "Сжатие видео",
  transcribe: "Распознавание речи",
  summarize: "Главы и конспект",
  embed: "Подготовка к поиску",
  quiz: "Квиз",
};

const stepStates: Record<Step["status"], string> = {
  pending: "ждёт",
  running: "идёт",
  done: "готово",
  failed: "ошибка",
};

type ProcessingProps = {
  status: LectureStatus;
  queuePosition: number | null;
  steps: Step[];
  onRetry: () => void;
  retrying: boolean;
  retryError: Error | null;
  stalled: boolean;
};

function headline(status: LectureStatus, queuePosition: number | null) {
  if (status === "failed") return "Обработка остановилась";
  if (status === "waiting_quota") return "Ждём свободный лимит обработки";
  if (status === "queued") {
    return queuePosition && queuePosition > 0 ? `В очереди, перед вами ${queuePosition}` : "В очереди";
  }
  return "Лекция обрабатывается";
}

function retryMessage(error: Error) {
  if (error instanceof ApiError) {
    const detail = detailOf(error.body);
    if (typeof detail === "string") return detail;
  }
  return "Не удалось перезапустить обработку. Попробуйте ещё раз.";
}

export function Processing({ status, queuePosition, steps, onRetry, retrying, retryError, stalled }: ProcessingProps) {
  const visible = steps
    .filter((step) => step.step !== "quiz")
    .sort((a, b) => stepOrder.indexOf(a.step) - stepOrder.indexOf(b.step));
  const failed = status === "failed";

  return (
    <section
      className={failed ? "processing processing--failed" : "processing"}
      aria-labelledby="lecture-processing"
    >
      <div className="processing__head">
        <h2 id="lecture-processing" className="processing__title" aria-live="polite">
          {headline(status, queuePosition)}
        </h2>
        {failed && (
          <Button variant="secondary" size="sm" onClick={onRetry} loading={retrying}>
            Повторить
          </Button>
        )}
      </div>
      {!failed && (
        <p className="processing__note">
          Страница обновится сама. Конспект и главы появятся здесь, как только будут готовы.
        </p>
      )}
      {stalled && (
        <p className="processing__error" role="status">
          Не получается узнать статус обработки. Пробуем снова, данные могут быть устаревшими.
        </p>
      )}
      {retryError && (
        <p className="processing__error" role="alert">
          {retryMessage(retryError)}
        </p>
      )}
      {visible.length > 0 && (
        <ol className="processing__steps">
          {visible.map((step) => (
            <li key={step.step} className={`processing__step processing__step--${step.status}`}>
              {step.status === "running" ? (
                <Progress label={stepLabels[step.step]} value={step.progress * 100} />
              ) : (
                <div className="processing__row">
                  <span className="processing__name">{stepLabels[step.step]}</span>
                  <span className="processing__state">{stepStates[step.status]}</span>
                </div>
              )}
              {step.status === "failed" && step.error && <p className="processing__reason">{step.error}</p>}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
