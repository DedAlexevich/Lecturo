import { useCallback, useState } from "react";
import { api } from "../../api/client";
import { getWebApp, openExternalLink } from "../../telegram/sdk";
import { useToast } from "../../ui/Toast";
import { Button } from "../../ui/Button";
import { nextLinkStep } from "./exportLink";

export type ExportFormat = "pdf" | "md" | "srt" | "vtt";
export type LinkResult = { url: string; expires_at: string } | number;
export type LinkRequester = (format: ExportFormat) => Promise<LinkResult>;

type Format = ExportFormat;

const labels: Record<Format, string> = { pdf: "PDF", md: "Markdown", srt: "SRT", vtt: "VTT" };

async function requestLink(lectureId: string, format: "pdf" | "srt" | "vtt") {
  const { data, response } = await api.POST("/api/v1/lectures/{lecture_id}/exports/{export_format}/link", {
    params: { path: { lecture_id: lectureId, export_format: format } },
  });
  return data === undefined ? response.status : data;
}

async function checkLink(url: string) {
  const controller = new AbortController();
  try {
    const response = await fetch(url, { cache: "no-store", credentials: "omit", redirect: "manual", signal: controller.signal });
    return response.status;
  } catch {
    return 0;
  } finally {
    controller.abort();
  }
}

function failureMessage(status: number) {
  if (status === 409) return "Файл ещё не готов, попробуйте позже.";
  if (status === 404) return "Лекция не найдена или ссылка больше не работает.";
  if (status === 401) return "Ссылка на скачивание устарела, попробуйте ещё раз.";
  if (status === 429) return "Слишком много запросов, попробуйте через несколько минут.";
  return "Не удалось скачать файл. Попробуйте ещё раз.";
}

const PREPARED_LINK_MS = 90_000;

type ExportActionsProps = {
  lectureId: string;
  ready: boolean;
  hasSegments: boolean;
};

export function ExportActions({ lectureId, ready, hasSegments }: ExportActionsProps) {
  const available: Format[] = [...(ready ? (["pdf"] as const) : []), ...(hasSegments ? (["srt", "vtt"] as const) : [])];
  const request = useCallback((format: Format) => requestLink(lectureId, format as "pdf" | "srt" | "vtt"), [lectureId]);
  return <ExportButtons request={request} available={available} />;
}

type ExportButtonsProps = {
  request: LinkRequester;
  available: Format[];
};

export function ExportButtons({ request, available }: ExportButtonsProps) {
  const toast = useToast();
  const [busy, setBusy] = useState<Format | null>(null);
  const [prepared, setPrepared] = useState<{ format: Format; url: string; expiresAt: number } | null>(null);
  const [failed, setFailed] = useState<Format | null>(null);

  const download = async (format: Format, url: string) => {
    let link = url;
    let refreshed = false;
    for (;;) {
      const step = nextLinkStep(await checkLink(link), refreshed);
      if (step === "open") {
        setFailed(null);
        openExternalLink(link);
        return;
      }
      if (step === "fail") {
        setFailed(format);
        return;
      }
      refreshed = true;
      const result = await request(format);
      if (typeof result === "number") {
        setFailed(null);
        toast.show(failureMessage(result), "error");
        return;
      }
      link = result.url;
    }
  };

  const run = async (format: Format) => {
    if (failed !== format) setFailed(null);
    if (prepared?.format === format && Date.now() < prepared.expiresAt) {
      openExternalLink(prepared.url);
      setPrepared(null);
      return;
    }
    setPrepared(null);
    setBusy(format);
    try {
      const result = await request(format);
      if (typeof result === "number") {
        setFailed(null);
        toast.show(failureMessage(result), "error");
        return;
      }
      if (getWebApp()) {
        setPrepared({ format, url: result.url, expiresAt: Date.now() + PREPARED_LINK_MS });
      } else {
        await download(format, result.url);
      }
    } catch {
      toast.show("Не удалось скачать файл. Проверьте соединение.", "error");
    } finally {
      setBusy(null);
    }
  };

  if (available.length === 0) return null;
  const failedLabel = failed ? labels[failed] : undefined;

  return (
    <>
      <div className="lecture__export" role="group" aria-label="Скачать">
        <span className="lecture__export-label">Скачать</span>
        {available.map((format) => (
          <Button
            key={format}
            variant="secondary"
            size="sm"
            loading={busy === format}
            disabled={busy !== null && busy !== format}
            onClick={() => void run(format)}
          >
            {prepared?.format === format ? `Открыть ${labels[format]}` : labels[format]}
          </Button>
        ))}
      </div>
      {failed && (
        <div className="lecture__export-error" role="alert">
          <p>Не удалось скачать {failedLabel}. Сервер не отдал файл.</p>
          <Button variant="secondary" size="sm" loading={busy === failed} disabled={busy !== null && busy !== failed} onClick={() => void run(failed)}>
            Попробовать снова
          </Button>
        </div>
      )}
    </>
  );
}
