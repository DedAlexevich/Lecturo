import type { components } from "../../api/schema";
import type { LectureProgress, LectureStatus } from "./queries";

type StepName = components["schemas"]["StepName"];

export const statusLabels: Record<LectureStatus, string> = {
  queued: "В очереди",
  waiting_quota: "Ждёт лимита",
  processing: "Обрабатывается",
  ready: "Готово",
  failed: "Ошибка",
};

const stepLabels: Record<StepName, string> = {
  download: "Скачиваем",
  audio: "Извлекаем звук",
  video: "Сжимаем видео",
  transcribe: "Распознаём речь",
  summarize: "Пишем конспект и главы",
  embed: "Готовим поиск",
  quiz: "Собираем квиз",
};

export function formatDuration(seconds: number | null) {
  if (seconds === null) return "—";
  const minutes = Math.round(seconds / 60);
  if (minutes < 1) return "меньше минуты";
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours === 0) return `${rest} мин`;
  return rest === 0 ? `${hours} ч` : `${hours} ч ${rest} мин`;
}

const dateFormat = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short" });
const dateWithYearFormat = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", year: "numeric" });

export function formatDate(value: string) {
  const date = new Date(value);
  const format = date.getFullYear() === new Date().getFullYear() ? dateFormat : dateWithYearFormat;
  return format.format(date).replace(".", "");
}

export function runningStep(progress: LectureProgress | undefined) {
  const running = progress?.steps.find((step) => step.status === "running");
  if (!running) return { label: "Обрабатываем" };
  return { label: stepLabels[running.step], value: running.progress * 100 };
}

const lectureForms = ["лекция", "лекции", "лекций"];

export function lecturesCount(count: number) {
  const tens = count % 100;
  const ones = count % 10;
  let form = lectureForms[2];
  if (tens < 11 || tens > 14) {
    if (ones === 1) form = lectureForms[0];
    else if (ones >= 2 && ones <= 4) form = lectureForms[1];
  }
  return `${count} ${form}`;
}
