import { api } from "../../api/client";
import { ApiError } from "../../app/queryClient";
import { toLocalResultPayload } from "../storage";
import type { LocalLecture } from "../storage";

export async function saveToAccount(lecture: LocalLecture) {
  const { data, error, response } = await api.POST("/api/v1/local-results", {
    body: toLocalResultPayload(lecture),
  });
  if (data === undefined) throw new ApiError(response.status, error);
  return data;
}

export function syncError(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 401) return "Сессия истекла. Войдите в аккаунт и попробуйте снова.";
    if (error.status === 422) return "Сервер не смог принять результат. Проверьте запись и попробуйте снова.";
    if (error.status === 429) return "Достигнут лимит сохранений. Попробуйте позже.";
    if (error.status === 403) return "Для сохранения нужно согласие на передачу данных. Попробуйте снова.";
  }
  return "Не удалось сохранить результат. Проверьте соединение и попробуйте снова.";
}
