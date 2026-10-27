import type { components } from "../../api/schema";
import { detailOf } from "../../features/upload/errors";
import { ApiError } from "../../app/queryClient";
import { Button } from "../../ui/Button";
import { Progress } from "../../ui/Progress";
import { etaText, headline, stepHint, stepLabel, stepProgress } from "./processingView";

type LectureStatus = components["schemas"]["LectureStatus"];
type Step = components["schemas"]["StepOut"];

const stepOrder: Step["step"][] = ["download", "audio", "transcribe", "summarize", "embed", "video"];

const stepStates: Record<Step["status"], string> = {
  pending: "ждёт",
  running: "идёт",
  done: "готово",
  failed: "ошибка",
};

type ProcessingProps = {
  status: LectureStatus;
  queuePosition: number | null;
  etaSec: number | null;
  steps: Step[];
  onRetry: () => void;
  retrying: boolean;
  retryError: Error | null;
  stalled: boolean;
};

function retryMessage(error: Error) {
  if (error instanceof ApiError) {
    const detail = detailOf(error.body);
    if (typeof detail === "string") return detail;
  }
  return "Не удалось перезапустить обработку. Попробуйте ещё раз.";
}

export function Processing({ status, queuePosition, etaSec, steps, onRetry, retrying, retryError, stalled }: ProcessingProps) {
  const visible = steps
    .filter((step) => step.step !== "quiz")
    .sort((a, b) => stepOrder.indexOf(a.step) - stepOrder.indexOf(b.step));
  const failed = status === "failed";
  const eta = failed ? null : etaText(etaSec);

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
      {eta && (
        <p className="processing__eta" role="status">
          {eta}
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
                <>
                  <Progress label={stepLabel(step)} value={stepProgress(step)} />
                  {stepHint(step) && <p className="processing__hint">{stepHint(step)}</p>}
                </>
              ) : (
                <div className="processing__row">
                  <span className="processing__name">{stepLabel(step)}</span>
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
