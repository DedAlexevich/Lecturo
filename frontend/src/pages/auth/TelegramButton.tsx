import { useEffect, useRef } from "react";
import { saveTelegramRedirect, telegramAuthUrl, type TelegramMode } from "./telegramParams";

const botUsername = import.meta.env.VITE_TELEGRAM_BOT_USERNAME as string | undefined;

export const telegramEnabled = Boolean(botUsername);

export function TelegramButton({ mode, redirect }: { mode: TelegramMode; redirect?: string }) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const host = container.current;
    if (!host || !botUsername) return;
    if (redirect) saveTelegramRedirect(redirect);
    const script = document.createElement("script");
    script.src = "https://telegram.org/js/telegram-widget.js?22";
    script.async = true;
    script.dataset.telegramLogin = botUsername;
    script.dataset.size = "large";
    script.dataset.radius = "8";
    script.dataset.requestAccess = "write";
    script.dataset.authUrl = telegramAuthUrl(window.location.origin, mode);
    host.append(script);
    return () => host.replaceChildren();
  }, [mode, redirect]);

  if (!botUsername) return null;
  return <div ref={container} className="auth-telegram" />;
}
