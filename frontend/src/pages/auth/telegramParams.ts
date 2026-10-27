import type { components } from "../../api/schema";

export type TelegramUser = components["schemas"]["TelegramLoginIn"];
export type TelegramMode = "login" | "link" | "delete";

const modes: readonly string[] = ["login", "link", "delete"];

export function isTelegramMode(value: string | undefined): value is TelegramMode {
  return value !== undefined && modes.includes(value);
}

export function telegramAuthUrl(origin: string, mode: TelegramMode) {
  return `${origin}/auth/telegram/${mode}`;
}

const REDIRECT_KEY = "lecturo.telegram-redirect";

export function saveTelegramRedirect(path: string) {
  try {
    sessionStorage.setItem(REDIRECT_KEY, path);
  } catch {
    return;
  }
}

export function takeTelegramRedirect(): string {
  try {
    const path = sessionStorage.getItem(REDIRECT_KEY);
    sessionStorage.removeItem(REDIRECT_KEY);
    return path && path.startsWith("/") && !path.startsWith("//") ? path : "/";
  } catch {
    return "/";
  }
}

function integer(value: string | null) {
  if (value === null || !/^\d{1,16}$/.test(value)) return null;
  return Number(value);
}

export function parseTelegramUser(params: URLSearchParams): TelegramUser | null {
  const id = integer(params.get("id"));
  const authDate = integer(params.get("auth_date"));
  const firstName = params.get("first_name");
  const hash = params.get("hash");
  if (id === null || authDate === null || !firstName || !hash) return null;
  const user: TelegramUser = { id, first_name: firstName, auth_date: authDate, hash };
  for (const key of ["last_name", "username", "photo_url"] as const) {
    const value = params.get(key);
    if (value) user[key] = value;
  }
  return user;
}
