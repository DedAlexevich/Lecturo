import { useEffect, useRef, useState } from "react";
import { buildLectureOutline, detectLlmPrecision, LLM_MODEL } from "../../local/llm";
import type { LlmPrecision, Outline } from "../../local/llm";
import type { LocalSegment } from "../../local/storage";
import { disposeWhisper } from "../../local/whisper";
import { Button } from "../../ui/Button";
import { Progress } from "../../ui/Progress";

type Stage = "idle" | "loading" | "outlining" | "error";

type LocalOutlineProps = {
  title: string;
  segments: LocalSegment[];
  hasOutline: boolean;
  onDone: (outline: Outline) => Promise<void> | void;
};

export function LocalOutline({ title, segments, hasOutline, onDone }: LocalOutlineProps) {
  const [precision, setPrecision] = useState<LlmPrecision | null>(null);
  const [stage, setStage] = useState<Stage>("idle");
  const [progress, setProgress] = useState<number>();
  const [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);
  const busy = stage === "loading" || stage === "outlining";

  useEffect(() => {
    let active = true;
    void detectLlmPrecision().then((value) => {
      if (active) setPrecision(value);
    });
    return () => {
      active = false;
      controller.current?.abort();
    };
  }, []);

  if (!precision) return null;

  async function start() {
    if (busy) return;
    disposeWhisper();
    const abort = new AbortController();
    controller.current = abort;
    setError("");
    setStage("loading");
    setProgress(undefined);
    try {
      const outline = await buildLectureOutline(title, segments, ({ stage: next, value }) => {
        setStage(next);
        setProgress(next === "loading" && value === 0 ? undefined : value * 100);
      }, abort.signal);
      if (abort.signal.aborted) return;
      await onDone(outline);
      setStage("idle");
    } catch (reason) {
      if (abort.signal.aborted) return;
      setError(reason instanceof Error ? reason.message : "неизвестная ошибка");
      setStage("error");
    } finally {
      if (controller.current === abort) controller.current = null;
    }
  }

  function cancel() {
    controller.current?.abort();
    controller.current = null;
    setStage("idle");
    setProgress(undefined);
  }

  const note = hasOutline
    ? `Составлены на этом устройстве моделью ${LLM_MODEL.label}.`
    : `Модель ${LLM_MODEL.label} разберёт расшифровку на видеокарте этого устройства, текст никуда не отправляется. При первом запуске модель загружается из интернета, ${LLM_MODEL.size}.`;

  return (
    <section className="local-outline" aria-labelledby="local-outline-title">
      <div className="local-outline__text">
        <h3 id="local-outline-title">Конспект и главы</h3>
        <p>{note}</p>
      </div>
      <div className="local-actions">
        {busy ? (
          <Button variant="secondary" onClick={cancel}>Отменить</Button>
        ) : (
          <Button variant={hasOutline ? "secondary" : "primary"} onClick={() => void start()}>
            {hasOutline ? "Составить заново" : "Составить конспект"}
          </Button>
        )}
      </div>
      {busy && (
        <div className="local-outline__status" aria-live="polite">
          <Progress label={stage === "loading" ? "Загрузка модели" : "Составление конспекта и глав"} value={progress} />
        </div>
      )}
      {stage === "error" && <p className="local-error local-outline__status" role="alert">Не удалось составить конспект: {error}</p>}
    </section>
  );
}
