import { buildExport } from "./format";
import type { ExportFormat } from "./format";
import type { LocalLecture } from "../storage/types";

export function downloadLecture(lecture: LocalLecture, format: ExportFormat) {
  const file = buildExport(lecture, format);
  const url = URL.createObjectURL(new Blob([file.content], { type: file.mime }));
  const link = document.createElement("a");
  link.href = url;
  link.download = file.name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
