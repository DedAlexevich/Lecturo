import { useEffect, useRef } from "react";
import { telegramBotUsername } from "../../telegram/bot";
import type { TelegramUser } from "./useAuthRequests";

declare global {
  interface Window {
    onLecturoTelegramAuth?: (user: TelegramUser) => void;
  }
}

const botUsername = telegramBotUsername;

export const telegramEnabled = Boolean(botUsername);

export function TelegramButton({ onAuth }: { onAuth: (user: TelegramUser) => void }) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const host = container.current;
    if (!host || !botUsername) return;
    window.onLecturoTelegramAuth = onAuth;
    const script = document.createElement("script");
    script.src = "https://telegram.org/js/telegram-widget.js?22";
    script.async = true;
    script.dataset.telegramLogin = botUsername;
    script.dataset.size = "large";
    script.dataset.radius = "8";
    script.dataset.requestAccess = "write";
    script.dataset.onauth = "onLecturoTelegramAuth(user)";
    host.append(script);
    return () => {
      host.replaceChildren();
      delete window.onLecturoTelegramAuth;
    };
  }, [onAuth]);

  if (!botUsername) return null;
  return <div ref={container} className="auth-telegram" />;
}
