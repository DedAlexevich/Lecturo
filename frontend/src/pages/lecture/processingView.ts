import type { components } from "../../api/schema";

type Step = components["schemas"]["StepOut"];
type LectureStatus = components["schemas"]["LectureStatus"];

const RECOGNITION_LIMIT = 0.95;

const stepLabels: Record<Step["step"], string> = {
  download: "Скачивание",
  audio: "Извлечение звука",
  video: "Сжатие видео",
  transcribe: "Распознавание речи",
  summarize: "Главы и конспект",
  embed: "Подготовка к поиску",
  quiz: "Квиз",
};

const transcribeStages: Record<string, string> = {
  upload: "Загрузка аудио в хранилище",
  recognize: "Распознавание идёт",
  fetch: "Получение результата",
};

export function formatDuration(seconds: number) {
  if (seconds < 60) return "меньше минуты";
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return `${minutes} мин`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `${hours} ч` : `${hours} ч ${rest} мин`;
}

export function stepLabel(step: Step) {
  if (step.step === "transcribe" && step.status === "running" && step.stage) {
    return transcribeStages[step.stage] ?? stepLabels.transcribe;
  }
  return stepLabels[step.step];
}

export function isIndeterminate(step: Step) {
  if (step.step !== "transcribe" || step.status !== "running") return false;
  if (step.stage === "upload" || step.stage === "fetch") return true;
  if (step.stage === "recognize") return step.expected_sec == null || step.progress >= RECOGNITION_LIMIT;
  return false;
}

export function stepHint(step: Step) {
  if (step.step !== "transcribe" || step.status !== "running") return null;
  if (step.stage === "fetch") return null;
  const expected = step.expected_sec;
  if (expected == null) return "Распознавание идёт, время зависит от длины записи";
  const usual = `обычно занимает около ${formatDuration(expected)}`;
  if (step.stage === "recognize" && step.progress >= RECOGNITION_LIMIT) return `Ещё немного: распознавание ${usual}`;
  return `Распознавание ${usual}`;
}

export function stepProgress(step: Step) {
  if (isIndeterminate(step)) return undefined;
  const value = step.progress * 100;
  if (step.step === "transcribe" && step.stage === "recognize") return Math.min(value, RECOGNITION_LIMIT * 100);
  return value;
}

export function headline(status: LectureStatus, queuePosition: number | null) {
  if (status === "failed") return "Обработка остановилась";
  if (status === "waiting_quota") return "Ждём свободный лимит обработки";
  if (status === "queued") {
    return queuePosition && queuePosition > 0 ? `В очереди, перед вами ${queuePosition}` : "Файл принят, готовим к обработке";
  }
  return "Лекция обрабатывается";
}

export function etaText(seconds: number | null | undefined) {
  if (seconds == null || seconds <= 0) return null;
  return `Осталось примерно ${formatDuration(seconds)}`;
}
