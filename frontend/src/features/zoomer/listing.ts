const clipUrl = /^\/zoomer\/[0-9a-f-]{36}\.mp4$/;

export function parseClipList(body: unknown): string[] {
  if (!Array.isArray(body)) return [];
  return body
    .filter(
      (entry): entry is { url: string } =>
        typeof entry === "object" && entry !== null && typeof entry.url === "string" && clipUrl.test(entry.url),
    )
    .map((entry) => entry.url);
}
