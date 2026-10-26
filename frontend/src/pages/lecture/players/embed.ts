import type { Player } from "./player";
import { rutube } from "./rutube";
import { vk } from "./vk";
import { youtube } from "./youtube";

export type EmbedHandlers = {
  onReady: (player: Player) => void;
  onTimeUpdate: (seconds: number) => void;
};

export type EmbedStart = {
  seconds: number;
  autoplay: boolean;
};

export type EmbedProvider = {
  name: string;
  hosts: string[];
  buildSrc: (url: URL, start: EmbedStart) => string;
  connect: (iframe: HTMLIFrameElement, handlers: EmbedHandlers) => () => void;
};

export type Embed = {
  url: URL;
  provider: EmbedProvider;
};

const providers = [youtube, rutube, vk];

export function resolveEmbed(embedUrl: string | null): Embed | null {
  if (!embedUrl) return null;
  let url: URL;
  try {
    url = new URL(embedUrl);
  } catch {
    return null;
  }
  if (url.protocol !== "https:") return null;
  const host = url.hostname.toLowerCase().replace(/^www\./, "");
  const provider = providers.find((item) => item.hosts.includes(host));
  return provider ? { url, provider } : null;
}

export function sameWindow(iframe: HTMLIFrameElement, event: MessageEvent) {
  return iframe.contentWindow !== null && event.source === iframe.contentWindow;
}
