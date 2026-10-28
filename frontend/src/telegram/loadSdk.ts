const sdkUrl = "https://telegram.org/js/telegram-web-app.js?62";
const launchParamsKey = "__telegram__initParams";
const sdkTimeoutMs = 4000;

export function isTelegramLaunch(hash: string, savedLaunchParams: string | null, hasWebviewProxy: boolean) {
  if (hasWebviewProxy) return true;
  if (new URLSearchParams(hash.replace(/^#/, "")).has("tgWebAppData")) return true;
  return savedLaunchParams?.includes("tgWebAppData") ?? false;
}

function savedLaunchParams() {
  try {
    return sessionStorage.getItem(launchParamsKey);
  } catch {
    return null;
  }
}

export function loadTelegramSdk() {
  const launched = isTelegramLaunch(window.location.hash, savedLaunchParams(), "TelegramWebviewProxy" in window);
  if (!launched || window.Telegram?.WebApp) return Promise.resolve();
  return new Promise<void>((resolve) => {
    const script = document.createElement("script");
    const timer = window.setTimeout(resolve, sdkTimeoutMs);
    const done = () => {
      window.clearTimeout(timer);
      resolve();
    };
    script.src = sdkUrl;
    script.onload = done;
    script.onerror = done;
    document.head.append(script);
  });
}
