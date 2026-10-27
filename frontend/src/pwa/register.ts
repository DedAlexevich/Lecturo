import { registerSW } from "virtual:pwa-register";

type UpdateState = { needRefresh: boolean };

let state: UpdateState = { needRefresh: false };
let applyUpdate: ((reload?: boolean) => Promise<void>) | null = null;
const listeners = new Set<() => void>();
const updateCheckInterval = 60 * 60 * 1000;

function setState(next: UpdateState) {
  state = next;
  listeners.forEach((listener) => listener());
}

export function subscribeUpdate(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getUpdateState() {
  return state;
}

export function dismissUpdate() {
  setState({ needRefresh: false });
}

export function applyServiceWorkerUpdate() {
  void applyUpdate?.(true);
}

export function registerServiceWorker() {
  applyUpdate = registerSW({
    immediate: true,
    onNeedRefresh() {
      setState({ needRefresh: true });
    },
    onOfflineReady() {},
    onRegisteredSW(_url, registration) {
      if (!registration) return;
      const checkForUpdate = () => {
        if (registration.installing || !navigator.onLine) return;
        void registration.update().catch(() => undefined);
      };
      setInterval(checkForUpdate, updateCheckInterval);
      document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") checkForUpdate();
      });
    },
  });
}
