import { useQuery } from "@tanstack/react-query";
import { api } from "../../../api/client";
import type { components } from "../../../api/schema";
import { ApiError } from "../../../app/queryClient";

export type LogService = components["schemas"]["LogService"];
export type LogLevel = components["schemas"]["LogLevel"];
export type LogLine = components["schemas"]["LogLineOut"];
export type ProcessingError = components["schemas"]["ProcessingErrorOut"];
export type BusinessEvent = components["schemas"]["BusinessEventOut"];
export type BusinessEventKind = components["schemas"]["BusinessEventKind"];

export const logServices: LogService[] = ["api", "worker", "bot", "caddy", "tusd"];

export const logLevels: { value: LogLevel | ""; label: string }[] = [
  { value: "", label: "Любой" },
  { value: "debug", label: "Debug и выше" },
  { value: "info", label: "Info и выше" },
  { value: "warning", label: "Warning и выше" },
  { value: "error", label: "Error и выше" },
  { value: "critical", label: "Critical" },
];

export const eventKindLabels: Record<BusinessEventKind, string> = {
  payment_created: "Платёж создан",
  payment_succeeded: "Платёж оплачен",
  payment_canceled: "Платёж отменён",
  payment_refunded: "Платёж возвращён",
  subscription_granted: "Подписка начислена",
  webhook_received: "Вебхук ЮKassa получен",
  webhook_rejected: "Вебхук ЮKassa отклонён",
  register: "Регистрация",
  login: "Вход",
  login_failed: "Неудачный вход",
  account_deleted: "Аккаунт удалён",
};

export const eventKinds = Object.keys(eventKindLabels) as BusinessEventKind[];

export const stepLabels: Record<ProcessingError["step"], string> = {
  download: "Скачивание",
  audio: "Аудио",
  video: "Видео",
  transcribe: "Расшифровка",
  summarize: "Конспект",
  embed: "Поиск",
  quiz: "Тест",
};

export const pageSize = 50;

export function useLogTail(service: LogService, level: LogLevel | "", query: string, lines: number) {
  return useQuery({
    queryKey: ["admin", "logs", service, level, query, lines],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/admin/logs/{service}", {
        params: { path: { service }, query: { level: level || undefined, q: query, lines } },
      });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });
}

export function useProcessingErrors(onlyFailed: boolean, offset: number) {
  return useQuery({
    queryKey: ["admin", "processing-errors", onlyFailed, offset],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/admin/processing-errors", {
        params: { query: { only_failed: onlyFailed, limit: pageSize, offset } },
      });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });
}

export function useBusinessEvents(kind: BusinessEventKind | "", offset: number) {
  return useQuery({
    queryKey: ["admin", "events", kind, offset],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/admin/events", {
        params: { query: { kind: kind || undefined, limit: pageSize, offset } },
      });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });
}
