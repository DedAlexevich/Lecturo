import type { ExportFile } from "./format";

export function saveFile(file: ExportFile) {
  const url = URL.createObjectURL(new Blob([file.content], { type: file.mime }));
  const link = document.createElement("a");
  link.href = url;
  link.download = file.name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function copyText(text: string, fallback: HTMLTextAreaElement | null) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    if (!fallback) return false;
    fallback.focus();
    fallback.select();
    fallback.setSelectionRange(0, text.length);
    try {
      return document.execCommand("copy");
    } catch {
      return false;
    }
  }
}
