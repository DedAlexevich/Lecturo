import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { components } from "../../api/schema";
import { ApiError } from "../../app/queryClient";
import { signIn } from "../../app/session";

export type VkMode = "login" | "link";
export type VkFlow = { mode: VkMode; redirect: string };
export type VkConsents = components["schemas"]["VkStartIn"];
export type VkCallback = components["schemas"]["VkCallbackIn"];

const FLOW_KEY = "lecturo.vk-flow";

type Result<T> = { data?: T; error?: unknown; response: Response };

function unwrap<T>(result: Result<T>): T {
  if (result.error !== undefined || !result.response.ok) throw new ApiError(result.response.status, result.error);
  return result.data as T;
}

export function saveVkFlow(flow: VkFlow) {
  try {
    sessionStorage.setItem(FLOW_KEY, JSON.stringify(flow));
  } catch {
    return;
  }
}

export function takeVkFlow(): VkFlow | null {
  try {
    const raw = sessionStorage.getItem(FLOW_KEY);
    sessionStorage.removeItem(FLOW_KEY);
    return raw ? (JSON.parse(raw) as VkFlow) : null;
  } catch {
    return null;
  }
}

export function useVkEnabled() {
  const providers = useQuery({
    queryKey: ["auth-providers"],
    queryFn: async () => unwrap(await api.GET("/api/v1/auth/providers")),
    staleTime: 5 * 60 * 1000,
  });
  return providers.data?.vk === true;
}

export function useVkStart(flow: VkFlow) {
  return useMutation({
    mutationFn: async (consents: VkConsents) =>
      flow.mode === "login"
        ? unwrap(await api.POST("/api/v1/auth/vk/start", { body: consents }))
        : unwrap(await api.POST("/api/v1/me/identities/vk/start")),
    onSuccess: ({ url }) => {
      saveVkFlow(flow);
      window.location.assign(url);
    },
  });
}

export function useVkLogin() {
  return useMutation({
    mutationFn: async (body: VkCallback) => unwrap(await api.POST("/api/v1/auth/vk/callback", { body })),
    onSuccess: (tokens) => signIn(tokens.access_token),
  });
}
