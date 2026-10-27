export type ExportFormat = "pdf" | "srt" | "vtt";

function sanitize(name: string) {
  return name.replace(/[\\/:*?"<>|]+/g, " ").replace(/\s+/g, " ").trim();
}

function decode(value: string) {
  try {
    return decodeURIComponent(value);
  } catch {
    return "";
  }
}

function fromDisposition(disposition: string | null) {
  if (!disposition) return "";
  const extended = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(disposition);
  const encoded = extended ? sanitize(decode(extended[1].trim())) : "";
  if (encoded) return encoded;
  const plain = /(?<!\*)filename\s*=\s*"?([^";]+)"?/i.exec(disposition);
  return plain ? sanitize(plain[1]) : "";
}

export function exportFileName(title: string, format: ExportFormat, disposition: string | null) {
  return fromDisposition(disposition) || `${sanitize(title) || "lecture"}.${format}`;
}
