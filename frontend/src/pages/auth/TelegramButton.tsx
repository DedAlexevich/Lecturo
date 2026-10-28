import { useEffect, useRef, useState } from "react";
import { useTelegramBotId } from "../../telegram/bot";
import { loadTelegramLogin, requestTelegramAuth, type TelegramLoginApi } from "../../telegram/login";
import { ProviderButton } from "./ProviderButton";
import type { TelegramUser } from "./useAuthRequests";

type TelegramButtonProps = {
  label: string;
  ariaLabel?: string;
  size?: "sm" | "md";
  fullWidth?: boolean;
  loading?: boolean;
  onAuth: (user: TelegramUser) => void;
  onError: (error: unknown) => void;
};

export function TelegramButton({
  label,
  ariaLabel,
  size = "md",
  fullWidth = false,
  loading = false,
  onAuth,
  onError,
}: TelegramButtonProps) {
  const telegramBotId = useTelegramBotId();
  const [login, setLogin] = useState<TelegramLoginApi>();
  const [failure, setFailure] = useState<unknown>();
  const [attempt, setAttempt] = useState(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (telegramBotId === undefined) return;
    let active = true;
    loadTelegramLogin().then(
      (api) => {
        if (active) setLogin(api);
      },
      (error: unknown) => {
        if (active) setFailure(error);
      },
    );
    return () => {
      active = false;
    };
  }, [attempt, telegramBotId]);

  if (telegramBotId === undefined) return null;
  const botId = telegramBotId;

  const start = () => {
    if (!login) {
      onError(failure);
      setFailure(undefined);
      setAttempt((value) => value + 1);
      return;
    }
    void requestTelegramAuth(login, botId).then((user) => {
      if (user && mounted.current) onAuth(user);
    });
  };

  return (
    <ProviderButton
      provider="telegram"
      label={label}
      aria-label={ariaLabel}
      size={size}
      fullWidth={fullWidth}
      loading={loading || (!login && failure === undefined)}
      onClick={start}
    />
  );
}
