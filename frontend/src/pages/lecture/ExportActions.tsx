import { useState } from "react";
import { api } from "../../api/client";
import { openExternalLink } from "../../telegram/sdk";
import { useToast } from "../../ui/Toast";
import { Button } from "../../ui/Button";

type Format = "pdf" | "srt" | "vtt";

const formats: { format: Format; label: string; needs: "ready" | "segments" }[] = [
  { format: "pdf", label: "PDF", needs: "ready" },
  { format: "srt", label: "SRT", needs: "segments" },
  { format: "vtt", label: "VTT", needs: "segments" },
];

async function requestLink(lectureId: string, format: Format) {
  const { data, response } = await api.POST("/api/v1/lectures/{lecture_id}/exports/{export_format}/link", {
    params: { path: { lecture_id: lectureId, export_format: format } },
  });
  return data === undefined ? response.status : data.url;
}

function failureMessage(status: number) {
  if (status === 409) return "Файл ещё не готов, попробуйте позже.";
  if (status === 404) return "Лекция не найдена.";
  if (status === 401) return "Войдите снова, чтобы скачать файл.";
  return "Не удалось скачать файл. Попробуйте ещё раз.";
}

type ExportActionsProps = {
  lectureId: string;
  ready: boolean;
  hasSegments: boolean;
};

export function ExportActions({ lectureId, ready, hasSegments }: ExportActionsProps) {
  const toast = useToast();
  const [busy, setBusy] = useState<Format | null>(null);

  const run = async (format: Format) => {
    setBusy(format);
    try {
      const result = await requestLink(lectureId, format);
      if (typeof result === "number") {
        toast.show(failureMessage(result), "error");
        return;
      }
      openExternalLink(result);
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
