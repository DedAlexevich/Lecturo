import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { ApiError } from "../app/queryClient";
import { parseBotId } from "./login";

export const telegramBotUsername = import.meta.env.VITE_TELEGRAM_BOT_USERNAME as string | undefined;

const buildTelegramBotId = parseBotId(import.meta.env.VITE_TELEGRAM_BOT_ID as string | undefined);

export const telegramBotUrl = telegramBotUsername ? `https://t.me/${telegramBotUsername}?start=notify` : null;

type Result<T> = { data?: T; error?: unknown; response: Response };

function unwrap<T>(result: Result<T>): T {
  if (result.error !== undefined || !result.response.ok) throw new ApiError(result.response.status, result.error);
  return result.data as T;
}

export function useTelegramBotId(): number | undefined {
  const providers = useQuery({
    queryKey: ["auth-providers"],
    queryFn: async () => unwrap(await api.GET("/api/v1/auth/providers")),
    staleTime: 5 * 60 * 1000,
  });
  return providers.data?.telegram_bot_id ?? buildTelegramBotId;
}

export function useTelegramEnabled(): boolean {
  return useTelegramBotId() !== undefined;
}
