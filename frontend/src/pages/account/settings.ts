import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { components } from "../../api/schema";
import { ApiError } from "../../app/queryClient";
import { meQueryKey } from "../../app/useMe";

export type Me = components["schemas"]["UserOut"];
export type Provider = components["schemas"]["IdentityOut"]["provider"];
export type TelegramUser = components["schemas"]["TelegramLoginIn"];

type Result<T> = { data?: T; error?: unknown; response: Response };

function unwrap<T>(result: Result<T>): T {
  if (result.error !== undefined || !result.response.ok) throw new ApiError(result.response.status, result.error);
  return result.data as T;
}

function detailOf(error: unknown) {
  if (!(error instanceof ApiError)) return undefined;
  const detail = (error.body as { detail?: unknown } | undefined)?.detail;
  return typeof detail === "string" ? detail : undefined;
}

export function settingsError(error: unknown, forbidden = "Не удалось подтвердить действие") {
  if (!(error instanceof ApiError)) return "Не удалось связаться с сервером. Проверьте интернет и попробуйте ещё раз";
  switch (error.status) {
    case 403:
      return forbidden;
    case 409:
      return detailOf(error) ?? "Действие сейчас недоступно";
    case 429:
      return "Слишком много попыток. Подождите немного и повторите";
    case 503:
      return "Сервис временно недоступен. Попробуйте позже";
    case 401:
      return detailOf(error) ?? "Не удалось подтвердить данные";
    case 422:
      return "Проверьте введённые данные";
    default:
      return "Что-то пошло не так. Попробуйте ещё раз чуть позже";
  }
}

function useMeMutation<V>(request: (variables: V) => Promise<Me>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: request,
    onSuccess: (me) => queryClient.setQueryData(meQueryKey, me),
  });
}

export function useRename() {
  return useMeMutation(async (displayName: string) =>
    unwrap(await api.PATCH("/api/v1/me", { body: { display_name: displayName } })),
  );
}

export function useChangePassword() {
  return useMutation({
    mutationFn: async (body: components["schemas"]["PasswordChangeIn"]) =>
      unwrap(await api.POST("/api/v1/me/password", { body })),
  });
}

export function useLinkTelegram() {
  return useMeMutation(async (body: TelegramUser) =>
    unwrap(await api.POST("/api/v1/me/identities/telegram", { body })),
  );
}

export function useLinkVk() {
  return useMeMutation(async (body: components["schemas"]["VkCallbackIn"]) =>
    unwrap(await api.POST("/api/v1/me/identities/vk", { body })),
  );
}

export function useLinkYandex() {
  return useMeMutation(async (body: components["schemas"]["YandexCallbackIn"]) =>
    unwrap(await api.POST("/api/v1/me/identities/yandex", { body })),
  );
}

export function useLinkEmail() {
  return useMeMutation(async (body: components["schemas"]["EmailIdentityIn"]) =>
    unwrap(await api.POST("/api/v1/me/identities/email", { body })),
  );
}

export function useUnlink() {
  return useMeMutation(async (provider: Provider) =>
    unwrap(await api.DELETE("/api/v1/me/identities/{provider}", { params: { path: { provider } } })),
  );
}

export function useRevokeAiTransfer() {
  return useMeMutation(async () => unwrap(await api.DELETE("/api/v1/me/consents/ai-transfer")));
}

export function useDeleteAccount() {
  return useMutation({
    mutationFn: async (body: components["schemas"]["AccountDeleteIn"]) =>
      unwrap(await api.POST("/api/v1/me/delete", { body })),
  });
}
