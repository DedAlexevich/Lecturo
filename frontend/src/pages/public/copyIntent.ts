const KEY = "lecturo:save-copy";
const LIFETIME_MS = 10 * 60 * 1000;

type Store = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export type CopyIntent = { token: string; lectureId: string | null };

function browserStore(): Store | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function rememberIntent(
  intent: CopyIntent,
  store: Store | null = browserStore(),
  now: number = Date.now(),
) {
  try {
    store?.setItem(KEY, JSON.stringify({ ...intent, at: now }));
  } catch {
    return;
  }
}

export function takeIntent(
  intent: CopyIntent,
  store: Store | null = browserStore(),
  now: number = Date.now(),
): boolean {
  if (store === null) return false;
  try {
    const raw = store.getItem(KEY);
    if (raw === null) return false;
    const saved = JSON.parse(raw) as
      (Partial<CopyIntent> & { at?: number }) | null;
    if (
      typeof saved?.at !== "number" ||
      now - saved.at > LIFETIME_MS ||
      now < saved.at
    ) {
      store.removeItem(KEY);
      return false;
    }
    if (
      saved.token !== intent.token ||
      (saved.lectureId ?? null) !== intent.lectureId
    )
      return false;
    store.removeItem(KEY);
    return true;
  } catch {
    return false;
  }
}
