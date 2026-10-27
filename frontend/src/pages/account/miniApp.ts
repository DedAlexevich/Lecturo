declare global {
  interface Window {
    Telegram?: { WebApp?: { initData?: string } };
  }
}

const initDataFromHash = new URLSearchParams(window.location.hash.slice(1)).get("tgWebAppData") ?? "";

export function getMiniAppInitData() {
  return window.Telegram?.WebApp?.initData || initDataFromHash;
}
