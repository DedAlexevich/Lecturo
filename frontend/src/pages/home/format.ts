import type { components } from "../../api/schema";
import { plural } from "../../lib/plural";
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

export function lecturesCount(count: number) {
  return `${count} ${plural(count, "лекция", "лекции", "лекций")}`;
}
