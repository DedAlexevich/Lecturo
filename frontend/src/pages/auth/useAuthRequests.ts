import { useMutation } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { components } from "../../api/schema";
import { ApiError } from "../../app/queryClient";
import { signIn } from "../../app/session";

export type TelegramUser = components["schemas"]["TelegramLoginIn"];

async function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): Promise<T> {
  if (result.error !== undefined || !result.response.ok) throw new ApiError(result.response.status, result.error);
  return result.data as T;
}

export function useLogin() {
  return useMutation({
    mutationFn: async (body: components["schemas"]["LoginIn"]) => unwrap(await api.POST("/api/v1/auth/login", { body })),
    onSuccess: (tokens) => signIn(tokens.access_token),
  });
}

export function useRegister() {
  return useMutation({
    mutationFn: async (body: components["schemas"]["RegisterIn"]) =>
      unwrap(await api.POST("/api/v1/auth/register", { body })),
    onSuccess: (tokens) => signIn(tokens.access_token),
  });
}

export function useTelegramLogin() {
  return useMutation({
    mutationFn: async (body: components["schemas"]["TelegramSignupIn"]) => unwrap(await api.POST("/api/v1/auth/telegram", { body })),
    onSuccess: (tokens) => signIn(tokens.access_token),
  });
}

export function useRequestPasswordReset() {
  return useMutation({
    mutationFn: async (email: string) =>
      unwrap(await api.POST("/api/v1/auth/password-reset/request", { body: { email } })),
  });
}

export function useConfirmPasswordReset() {
  return useMutation({
    mutationFn: async (body: components["schemas"]["PasswordResetIn"]) =>
      unwrap(await api.POST("/api/v1/auth/password-reset/confirm", { body })),
  });
}

export function useConfirmEmail() {
  return useMutation({
    mutationFn: async (token: string) => unwrap(await api.POST("/api/v1/auth/verify-email/confirm", { body: { token } })),
  });
}

export function useRequestEmailVerification() {
  return useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/auth/verify-email/request")),
  });
}
