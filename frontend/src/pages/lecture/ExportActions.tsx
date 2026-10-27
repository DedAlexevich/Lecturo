import { useState } from "react";
import { api } from "../../api/client";
import { useToast } from "../../ui/Toast";
import { Button } from "../../ui/Button";
import { exportFileName, type ExportFormat as Format } from "./exportFileName";

const formats: { format: Format; label: string; needs: "ready" | "segments" }[] = [
  { format: "pdf", label: "PDF", needs: "ready" },
  { format: "srt", label: "SRT", needs: "segments" },
  { format: "vtt", label: "VTT", needs: "segments" },
];

async function download(lectureId: string, format: Format) {
  const params = { path: { lecture_id: lectureId } };
  const result =
    format === "pdf"
      ? await api.GET("/api/v1/lectures/{lecture_id}/export.pdf", { params, parseAs: "blob" })
      : format === "srt"
        ? await api.GET("/api/v1/lectures/{lecture_id}/export.srt", { params, parseAs: "blob" })
        : await api.GET("/api/v1/lectures/{lecture_id}/export.vtt", { params, parseAs: "blob" });
  if (!result.response.ok || !(result.data instanceof Blob)) return result.response.status;
  return { blob: result.data, disposition: result.response.headers.get("Content-Disposition") };
}

function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

type ExportActionsProps = {
  lectureId: string;
  title: string;
  ready: boolean;
  hasSegments: boolean;
};

export function ExportActions({ lectureId, title, ready, hasSegments }: ExportActionsProps) {
  const toast = useToast();
  const [busy, setBusy] = useState<Format | null>(null);

  const run = async (format: Format) => {
    setBusy(format);
    try {
      const result = await download(lectureId, format);
      if (typeof result === "number") {
        toast.show(
          result === 501 ? "Этот формат пока не готов, попробуйте позже." : "Не удалось скачать файл.",
          "error",
        );
        return;
      }
      saveBlob(result.blob, exportFileName(title, format, result.disposition));
    } catch {
      toast.show("Не удалось скачать файл. Проверьте соединение.", "error");
    } finally {
      setBusy(null);
    }
  };

  const available = formats.filter(({ needs }) => (needs === "ready" ? ready : hasSegments));
  if (available.length === 0) return null;

  return (
    <div className="lecture__export" role="group" aria-label="Скачать">
      <span className="lecture__export-label">Скачать</span>
      {available.map(({ format, label }) => (
        <Button
          key={format}
          variant="secondary"
          size="sm"
          loading={busy === format}
          disabled={busy !== null && busy !== format}
          onClick={() => void run(format)}
        >
          {label}
        </Button>
      ))}
    </div>
  );
}
