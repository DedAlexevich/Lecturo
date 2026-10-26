import { sameWindow, type EmbedProvider } from "./embed";

type VkMessage = {
  event?: string;
  time?: number;
};

function vkTimecode(totalSeconds: number) {
  const seconds = Math.floor(totalSeconds);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours}h${minutes}m${seconds % 60}s`;
}

export const vk: EmbedProvider = {
  name: "VK Видео",
  hosts: ["vkvideo.ru", "vk.com", "vk.ru"],
  buildSrc(url, start) {
    const src = new URL(url);
    src.searchParams.set("js_api", "1");
    if (start.seconds > 0) src.searchParams.set("t", vkTimecode(start.seconds));
    if (start.autoplay) src.searchParams.set("autoplay", "1");
    return src.toString();
  },
  connect(iframe, { onReady, onTimeUpdate }) {
    let target = "*";
    let time = 0;

    const send = (message: Record<string, unknown>) => iframe.contentWindow?.postMessage(message, target);
    const init = () => send({ method: "init" });

    const onMessage = (event: MessageEvent) => {
      if (!sameWindow(iframe, event)) return;
      const message = event.data as VkMessage | null;
      if (!message || typeof message !== "object") return;
      target = event.origin;
      if (typeof message.time === "number") time = message.time;
      if (message.event === "inited") {
        onReady({
          seek: (seconds) => {
            time = Math.max(0, seconds);
            send({ method: "seek", time });
            onTimeUpdate(time);
          },
          play: () => send({ method: "play" }),
          pause: () => send({ method: "pause" }),
          getCurrentTime: () => time,
        });
      } else if (message.event === "timeupdate" || message.event === "seeked") {
        onTimeUpdate(time);
      }
    };

    window.addEventListener("message", onMessage);
    iframe.addEventListener("load", init);
    init();
    return () => {
      window.removeEventListener("message", onMessage);
      iframe.removeEventListener("load", init);
    };
  },
};
