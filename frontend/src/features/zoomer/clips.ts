import { parseClipListing } from "./listing";

let request: Promise<string[]> | null = null;

export function loadZoomerClips(): Promise<string[]> {
  request ??= fetch("/zoomer/", { headers: { Accept: "application/json" } })
    .then((response) => (response.ok ? response.json() : []))
    .then(parseClipListing)
    .catch(() => []);
  return request;
}
