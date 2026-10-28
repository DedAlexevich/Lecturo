export type TelegramAuthData = {
  id: number;
  first_name: string;
  last_name?: string;
  username?: string;
  photo_url?: string;
  auth_date: number;
  hash: string;
};

export type TelegramLoginOptions = { bot_id: number; request_access?: "write"; lang?: string };

export type TelegramLoginApi = {
  auth: (options: TelegramLoginOptions, callback: (data: TelegramAuthData | false) => void) => void;
};

const scriptUrl = "https://telegram.org/js/telegram-widget.js?22";

let loading: Promise<TelegramLoginApi> | undefined;

export function parseBotId(value: string | undefined) {
  const trimmed = value?.trim() ?? "";
  if (!/^[1-9]\d*$/.test(trimmed)) return undefined;
  const id = Number(trimmed);
  return Number.isSafeInteger(id) ? id : undefined;
}

export function requestTelegramAuth(login: TelegramLoginApi, botId: number) {
  return new Promise<TelegramAuthData | null>((resolve) =>
    login.auth({ bot_id: botId, request_access: "write", lang: "ru" }, (data) => resolve(data || null)),
  );
}

export function loadTelegramLogin() {
  const ready = window.Telegram?.Login;
  if (ready) return Promise.resolve(ready);
  loading ??= new Promise<TelegramLoginApi>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = scriptUrl;
    script.async = true;
    script.onload = () => {
      const login = window.Telegram?.Login;
      if (login) resolve(login);
      else reject(new Error("Telegram Login is unavailable"));
    };
    script.onerror = () => reject(new Error("Telegram Login is unavailable"));
    document.head.append(script);
  }).catch((error: unknown) => {
    loading = undefined;
    throw error;
  });
  return loading;
}
