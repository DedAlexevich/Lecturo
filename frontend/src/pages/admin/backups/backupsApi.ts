import { useQuery } from "@tanstack/react-query";
import { api, tokenStorage } from "../../../api/client";
import type { components } from "../../../api/schema";
import { ApiError } from "../../../app/queryClient";

export type Backup = components["schemas"]["BackupOut"];
export type BackupJob = components["schemas"]["BackupJobOut"];

export const backupsQueryKey = ["admin", "backups"] as const;

export const sourceLabels: Record<string, string> = {
  lecturo: "Плановый",
  manual: "Вручную",
  uploaded: "Загружен",
  "pre-restore": "Перед восстановлением",
  other: "Другой",
};

export const integrityLabels: Record<Backup["integrity"], string> = {
  ok: "Читается",
  broken: "Повреждён",
  encrypted: "Зашифрован",
};

export const jobStepLabels: Record<string, string> = {
  start: "Запуск",
  dump: "Снимаем дамп",
  maintenance: "Включаем режим обслуживания",
  waiting_workers: "Ждём, пока воркер закончит обработку",
  pre_restore_dump: "Сохраняем текущую базу",
  test_restore: "Пробное восстановление во временную базу",
  restore: "Восстанавливаем базу",
  migrate: "Применяем миграции",
  resume: "Возобновляем обработку лекций",
  finished: "Готово",
};

export function errorDetail(error: unknown, fallback: string) {
  if (error instanceof ApiError) {
    const detail = (error.body as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

export function useBackups() {
  return useQuery({
    queryKey: backupsQueryKey,
    refetchInterval: (query) => (query.state.data?.job?.state === "running" || query.state.data?.maintenance ? 2000 : false),
    retry: false,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/admin/backups");
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });
}

export function formatSize(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} КБ`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} МБ`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} ГБ`;
}

export async function downloadBackup(name: string) {
  const response = await fetch(`/api/v1/admin/backups/${encodeURIComponent(name)}/download`, {
    headers: { Authorization: `Bearer ${tokenStorage.get() ?? ""}` },
  });
  if (!response.ok) throw new ApiError(response.status, await response.json().catch(() => undefined));
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function uploadBackup(file: File, onProgress: (share: number) => void) {
  return new Promise<Backup>((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", "/api/v1/admin/backups/upload");
    request.setRequestHeader("Authorization", `Bearer ${tokenStorage.get() ?? ""}`);
    request.setRequestHeader("Content-Type", "application/octet-stream");
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    request.onerror = () => reject(new ApiError(0, undefined));
    request.onload = () => {
      let body: unknown;
      try {
        body = JSON.parse(request.responseText);
      } catch {
        body = undefined;
      }
      if (request.status >= 200 && request.status < 300) resolve(body as Backup);
      else reject(new ApiError(request.status, body));
    };
    request.send(file);
  });
}
