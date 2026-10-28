const reloadKey = "lecturo:preload-reload-at";
const reloadCooldownMs = 60 * 1000;

type ReloadStorage = Pick<Storage, "getItem" | "setItem">;

export function shouldReloadAfterPreloadError(storage: ReloadStorage, now: number) {
  try {
    const last = Number(storage.getItem(reloadKey));
    if (Number.isFinite(last) && last > 0 && now - last < reloadCooldownMs) return false;
    storage.setItem(reloadKey, String(now));
    return true;
  } catch {
    return false;
  }
}

export function reloadOnPreloadError() {
  window.addEventListener("vite:preloadError", (event) => {
    if (!shouldReloadAfterPreloadError(window.sessionStorage, Date.now())) return;
    event.preventDefault();
    window.location.reload();
  });
}
