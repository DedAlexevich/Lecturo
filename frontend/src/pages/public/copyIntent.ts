const KEY = "lecturo:save-copy";

type Store = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export type CopyIntent = { token: string; lectureId: string | null };

function browserStore(): Store | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function rememberIntent(intent: CopyIntent, store: Store | null = browserStore()) {
  try {
    store?.setItem(KEY, JSON.stringify(intent));
  } catch {
    return;
  }
}

export function takeIntent(intent: CopyIntent, store: Store | null = browserStore()): boolean {
  if (store === null) return false;
  try {
    const raw = store.getItem(KEY);
    if (raw === null) return false;
    const saved = JSON.parse(raw) as Partial<CopyIntent> | null;
    if (saved?.token !== intent.token || (saved.lectureId ?? null) !== intent.lectureId) return false;
    store.removeItem(KEY);
    return true;
  } catch {
    return false;
  }
}
