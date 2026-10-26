declare global {
  interface Window {
    Telegram?: { WebApp?: { initData?: string } };
  }
}

function readInitData() {
  const fromWebApp = window.Telegram?.WebApp?.initData;
  if (fromWebApp) return fromWebApp;
  const fromHash = new URLSearchParams(window.location.hash.slice(1)).get("tgWebAppData");
  return fromHash ?? "";
}

export const miniAppInitData = readInitData();
