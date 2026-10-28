import { parseClipList } from "./listing";

let request: Promise<string[]> | null = null;

export function loadZoomerClips(): Promise<string[]> {
  request ??= fetch("/api/v1/zoomer/videos", { headers: { Accept: "application/json" } })
    .then((response) => (response.ok ? response.json() : []))
    .then(parseClipList)
    .catch(() => []);
  return request;
}
