import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { components } from "../../api/schema";
import { ApiError } from "../../app/queryClient";
import { signIn } from "../../app/session";

export type YandexMode = "login" | "link";
export type YandexFlow = { mode: YandexMode; redirect: string };
export type StoredYandexFlow = YandexFlow & { nonce: string };
export type YandexConsents = components["schemas"]["YandexStartIn"];
export type YandexCallback = components["schemas"]["YandexCallbackIn"];

const FLOW_KEY = "lecturo.yandex-flow";

type Result<T> = { data?: T; error?: unknown; response: Response };

function unwrap<T>(result: Result<T>): T {
  if (result.error !== undefined || !result.response.ok) throw new ApiError(result.response.status, result.error);
  return result.data as T;
}

export function saveYandexFlow(flow: StoredYandexFlow) {
  try {
    sessionStorage.setItem(FLOW_KEY, JSON.stringify(flow));
  } catch {
    return;
  }
}

export function takeYandexFlow(): StoredYandexFlow | null {
  try {
    const raw = sessionStorage.getItem(FLOW_KEY);
    sessionStorage.removeItem(FLOW_KEY);
    return raw ? (JSON.parse(raw) as StoredYandexFlow) : null;
  } catch {
    return null;
  }
}

export function useYandexEnabled() {
  const providers = useQuery({
    queryKey: ["auth-providers"],
    queryFn: async () => unwrap(await api.GET("/api/v1/auth/providers")),
    staleTime: 5 * 60 * 1000,
  });
  return providers.data?.yandex === true;
}

export function useYandexStart(flow: YandexFlow) {
  return useMutation({
    mutationFn: async (consents: YandexConsents) =>
      flow.mode === "login"
        ? unwrap(await api.POST("/api/v1/auth/yandex/start", { body: consents }))
        : unwrap(await api.POST("/api/v1/me/identities/yandex/start")),
    onSuccess: ({ url, nonce }) => {
      saveYandexFlow({ ...flow, nonce });
      window.location.assign(url);
    },
  });
}

export function useYandexLogin() {
  return useMutation({
    mutationFn: async (body: YandexCallback) => unwrap(await api.POST("/api/v1/auth/yandex/callback", { body })),
    onSuccess: (tokens) => signIn(tokens.access_token),
  });
}
