import { registerSW } from "virtual:pwa-register";

export function registerServiceWorker() {
  registerSW({ immediate: true });
}
