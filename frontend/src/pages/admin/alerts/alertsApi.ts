import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../../api/client";
import type { components } from "../../../api/schema";
import { ApiError } from "../../../app/queryClient";

export type AlertKind = components["schemas"]["AlertKind"];
export type AlertSettings = components["schemas"]["AlertSettingsOut"];
export type AlertSettingsInput = components["schemas"]["AlertSettingsIn"];

export const alertSettingsQueryKey = ["admin", "alerts", "settings"] as const;

export const alertKinds: { kind: AlertKind; title: string; when: string }[] = [
  { kind: "service_down", title: "Падение сервисов", when: "Сайт не отвечает три проверки подряд или упала служба на сервере" },
  { kind: "queue_stalled", title: "Очередь обработки", when: "Лекции ждут в очереди дольше часа, а воркер ничего не обрабатывает" },
  { kind: "disk_low", title: "Место на диске", when: "Раздел с данными, бэкапами или системой занят на 85% и больше" },
  { kind: "memory_low", title: "Память", when: "На сервере занято 90% памяти и больше" },
  { kind: "backup", title: "Бэкапы", when: "Ночной бэкап упал или самому свежему дампу больше 26 часов" },
  { kind: "payment", title: "Платежи", when: "Прошла оплата или возврат в ЮKassa" },
  { kind: "webhook_error", title: "Ошибки вебхуков ЮKassa", when: "Уведомление ЮKassa не принято: подделка, неверная сумма, ЮKassa не отвечает" },
];

export function useAlertSettings() {
  return useQuery({
    queryKey: alertSettingsQueryKey,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/admin/alerts/settings");
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });
}

export function useSaveAlertSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: AlertSettingsInput) => {
      const { data, error, response } = await api.PUT("/api/v1/admin/alerts/settings", { body });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(alertSettingsQueryKey, data);
      void queryClient.invalidateQueries({ queryKey: ["admin", "audit"] });
    },
  });
}

export function useSendTestAlert() {
  return useMutation({
    mutationFn: async () => {
      const { error, response } = await api.POST("/api/v1/admin/alerts/test");
      if (!response.ok) throw new ApiError(response.status, error);
    },
  });
}
