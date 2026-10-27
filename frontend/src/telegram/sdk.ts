export type WebApp = {
  initData: string;
  colorScheme: "light" | "dark";
  themeParams: Record<string, string | undefined>;
  ready: () => void;
  expand: () => void;
  onEvent: (event: string, callback: () => void) => void;
  offEvent: (event: string, callback: () => void) => void;
  openLink: (url: string) => void;
  openTelegramLink?: (url: string) => void;
  BackButton: {
    show: () => void;
    hide: () => void;
    onClick: (callback: () => void) => void;
    offClick: (callback: () => void) => void;
  };
};

declare global {
  interface Window {
    Telegram?: { WebApp?: WebApp };
  }
}

export function getWebApp() {
  const app = window.Telegram?.WebApp;
  return app?.initData ? app : undefined;
}

export function openExternalLink(value: string) {
  let url: URL;
  try {
    url = new URL(value, window.location.origin);
  } catch {
    return;
  }
  if (!["https:", "http:"].includes(url.protocol) || url.username || url.password) return;
  const app = getWebApp();
  if (app) app.openLink(url.href);
  else window.location.assign(url.href);
}

export function bindTheme(app: WebApp) {
  const root = document.documentElement;
  const previousTheme = root.getAttribute("data-theme");
  const tokens: Record<string, string> = {
    "--color-bg": "secondary_bg_color",
    "--color-surface": "bg_color",
    "--color-surface-sunken": "section_bg_color",
    "--color-text": "text_color",
    "--color-text-muted": "hint_color",
    "--color-data": "link_color",
    "--color-focus": "link_color",
    "--color-accent": "button_color",
    "--color-accent-hover": "button_color",
    "--color-on-accent": "button_text_color",
    "--color-danger": "destructive_text_color",
  };
  const previous = Object.fromEntries(Object.keys(tokens).map((key) => [key, root.style.getPropertyValue(key)]));
  const update = () => {
    root.setAttribute("data-theme", app.colorScheme);
    for (const [token, key] of Object.entries(tokens)) {
      const color = app.themeParams[key];
      if (color && /^#[\da-f]{6}$/i.test(color)) root.style.setProperty(token, color);
      else root.style.removeProperty(token);
    }
  };
  update();
  app.onEvent("themeChanged", update);
  return () => {
    app.offEvent("themeChanged", update);
    if (previousTheme === null) root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", previousTheme);
    for (const [token, value] of Object.entries(previous)) {
      if (value) root.style.setProperty(token, value);
      else root.style.removeProperty(token);
    }
  };
}
