import { useState } from "react";
import { api } from "../../api/client";
import { getWebApp, openExternalLink } from "../../telegram/sdk";
import { Button } from "../../ui/Button";
import { useToast } from "../../ui/Toast";

const PREPARED_LINK_MS = 90_000;

function failureMessage(status: number) {
  if (status === 403) return "PDF памятки доступен только с подпиской.";
  if (status === 404) return "Памятка не найдена. Обновите страницу.";
  if (status === 401) return "Войдите снова, чтобы открыть PDF.";
  return "Не удалось подготовить PDF. Попробуйте ещё раз.";
}

function TelegramPrintButton({ courseId }: { courseId: string }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [prepared, setPrepared] = useState<{ url: string; expiresAt: number } | null>(null);

  const run = async () => {
    if (prepared && Date.now() < prepared.expiresAt) {
      openExternalLink(prepared.url);
      setPrepared(null);
      return;
    }
    setPrepared(null);
    setBusy(true);
    try {
      const { data, response } = await api.POST("/api/v1/courses/{course_id}/exam-sheet/exports/pdf/link", {
        params: { path: { course_id: courseId } },
      });
      if (data === undefined) {
        toast.show(failureMessage(response.status), "error");
        return;
      }
      setPrepared({ url: data.url, expiresAt: Date.now() + PREPARED_LINK_MS });
    } catch {
      toast.show("Не удалось подготовить PDF. Проверьте соединение.", "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Button variant="secondary" loading={busy} onClick={() => void run()}>
      {prepared ? "Открыть PDF" : "Распечатать"}
    </Button>
  );
}

export function PrintButton({ courseId }: { courseId: string }) {
  if (getWebApp()) return <TelegramPrintButton courseId={courseId} />;
  return (
    <Button variant="secondary" onClick={() => window.print()}>
      Распечатать
    </Button>
  );
}
