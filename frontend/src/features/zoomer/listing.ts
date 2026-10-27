const clipName = /\.(mp4|webm)$/i;

export function parseClipListing(body: unknown): string[] {
  if (!Array.isArray(body)) return [];
  return body
    .filter(
      (entry): entry is { name: string } =>
        typeof entry === "object" &&
        entry !== null &&
        typeof entry.name === "string" &&
        entry.is_dir !== true &&
        clipName.test(entry.name),
    )
    .map((entry) => entry.name)
    .sort()
    .map((name) => `/zoomer/${encodeURIComponent(name)}`);
}
