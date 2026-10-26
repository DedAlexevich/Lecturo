import type { EmbedProvider } from "./embed";

const API_SRC = "https://www.youtube.com/iframe_api";
const POLL_INTERVAL_MS = 250;

type YouTubePlayer = {
  seekTo: (seconds: number, allowSeekAhead: boolean) => void;
  playVideo: () => void;
  pauseVideo: () => void;
  getCurrentTime: () => number;
};

type YouTubeApi = {
  Player: new (
    iframe: HTMLIFrameElement,
    options: { events: { onReady: (event: { target: YouTubePlayer }) => void } },
  ) => YouTubePlayer;
};

declare global {
  interface Window {
    YT?: Partial<YouTubeApi>;
    onYouTubeIframeAPIReady?: () => void;
  }
}

let apiPromise: Promise<YouTubeApi> | null = null;

function loadApi() {
  if (window.YT?.Player) return Promise.resolve(window.YT as YouTubeApi);
  if (apiPromise) return apiPromise;
  apiPromise = new Promise<YouTubeApi>((resolve, reject) => {
    const previous = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => {
      previous?.();
      resolve(window.YT as YouTubeApi);
    };
    const script = document.createElement("script");
    script.src = API_SRC;
    script.async = true;
    script.onerror = () => {
      script.remove();
      apiPromise = null;
      reject(new Error("YouTube API unavailable"));
    };
    document.head.append(script);
  });
  return apiPromise;
}

export const youtube: EmbedProvider = {
  name: "YouTube",
  hosts: ["youtube.com", "youtube-nocookie.com"],
  buildSrc(url, start) {
    const src = new URL(url);
    src.searchParams.set("enablejsapi", "1");
    src.searchParams.set("origin", window.location.origin);
    src.searchParams.set("rel", "0");
    src.searchParams.set("playsinline", "1");
    if (start.seconds > 0) src.searchParams.set("start", String(Math.floor(start.seconds)));
    if (start.autoplay) src.searchParams.set("autoplay", "1");
    return src.toString();
  },
  connect(iframe, { onReady, onTimeUpdate }) {
    let active = true;
    let timer: number | undefined;

    loadApi()
      .then((api) => {
        if (!active) return;
        new api.Player(iframe, {
          events: {
            onReady: ({ target }) => {
              if (!active) return;
              let reported = -1;
              timer = window.setInterval(() => {
                const time = target.getCurrentTime();
                if (time === reported) return;
                reported = time;
                onTimeUpdate(time);
              }, POLL_INTERVAL_MS);
              onReady({
                seek: (seconds) => {
                  target.seekTo(Math.max(0, seconds), true);
                  onTimeUpdate(Math.max(0, seconds));
                },
                play: () => target.playVideo(),
                pause: () => target.pauseVideo(),
                getCurrentTime: () => target.getCurrentTime(),
              });
            },
          },
        });
      })
      .catch(() => undefined);

    return () => {
      active = false;
      window.clearInterval(timer);
    };
  },
};
