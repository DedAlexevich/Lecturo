import { sameWindow, withTime, type EmbedProvider } from "./embed";

type RutubeMessage = {
  type?: string;
  data?: { time?: number };
};

function parse(data: unknown): RutubeMessage | null {
  if (typeof data !== "string") return null;
  try {
    const message: unknown = JSON.parse(data);
    return message && typeof message === "object" ? (message as RutubeMessage) : null;
  } catch {
    return null;
  }
}

export const rutube: EmbedProvider = {
  name: "Rutube",
  hosts: ["rutube.ru"],
  buildSrc(url, start) {
    const src = new URL(url);
    if (start.seconds > 0) src.searchParams.set("t", String(Math.floor(start.seconds)));
    if (start.autoplay) src.searchParams.set("autoplay", "1");
    return src.toString();
  },
  linkAt(sourceUrl, seconds) {
    return withTime(sourceUrl, "t", seconds >= 1 ? String(Math.floor(seconds)) : null);
  },
  connect(iframe, { onReady, onTimeUpdate }) {
    const origin = new URL(iframe.src).origin;
    let time = 0;

    const send = (type: string, data: Record<string, unknown> = {}) =>
      iframe.contentWindow?.postMessage(JSON.stringify({ type, data }), origin);

    const onMessage = (event: MessageEvent) => {
      if (!sameWindow(iframe, event)) return;
      const message = parse(event.data);
      if (!message) return;
      if (message.type === "player:ready") {
        onReady({
          seek: (seconds) => {
            time = Math.max(0, seconds);
            send("player:setCurrentTime", { time });
            onTimeUpdate(time);
          },
          play: () => send("player:play"),
          pause: () => send("player:pause"),
          getCurrentTime: () => time,
        });
      } else if (message.type === "player:currentTime" && typeof message.data?.time === "number") {
        time = message.data.time;
        onTimeUpdate(time);
      }
    };

    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  },
};
