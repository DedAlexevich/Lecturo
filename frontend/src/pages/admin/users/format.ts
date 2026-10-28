import type { components } from "../../../api/schema";
import type { LectureStatus } from "./api";

type AuthProvider = components["schemas"]["AuthProvider"];
type PaymentStatus = components["schemas"]["PaymentStatus"];
type SourceType = components["schemas"]["SourceType"];

export const providerLabels: Record<AuthProvider, string> = {
  email: "Почта и пароль",
  telegram: "Telegram",
  vk: "VK",
  yandex: "Яндекс",
};

export const lectureStatusLabels: Record<LectureStatus, string> = {
  queued: "В очереди",
  waiting_quota: "Ждёт лимита",
  processing: "Обрабатывается",
  ready: "Готова",
  failed: "Ошибка",
};

export const paymentStatusLabels: Record<PaymentStatus, string> = {
  pending: "Ожидает оплаты",
  succeeded: "Оплачен",
  canceled: "Отменён",
  refunded: "Возвращён",
};

export const sourceLabels: Record<SourceType, string> = {
  upload: "Файл",
  link: "Ссылка",
  local: "На устройстве",
};

const hours = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 });
const count = new Intl.NumberFormat("ru-RU");

export function formatHours(seconds: number) {
  return `${hours.format(seconds / 3600)} ч`;
}

export function formatCount(value: number) {
  return count.format(value);
}

export function kopecksToRubles(kopecks: number) {
  return kopecks / 100;
}
