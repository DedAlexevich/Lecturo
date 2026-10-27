import { registerSW } from "virtual:pwa-register";

type UpdateState = { needRefresh: boolean };

let state: UpdateState = { needRefresh: false };
let applyUpdate: ((reload?: boolean) => Promise<void>) | null = null;
const listeners = new Set<() => void>();

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
  });
}
