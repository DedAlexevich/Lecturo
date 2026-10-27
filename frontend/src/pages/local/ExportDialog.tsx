import { useRef, useState } from "react";
import { buildExport, chooseLocalDelivery, chooseShareMode, copyText, saveFile } from "../../local/export";
import type { ExportFile, ExportFormat } from "../../local/export";
import type { LocalLecture } from "../../local/storage";
import { getWebApp } from "../../telegram/sdk";
import { Button } from "../../ui/Button";
import { Dialog } from "../../ui/Dialog";

export const exportLabels: Record<ExportFormat, string> = { srt: "SRT", vtt: "VTT", md: "Markdown" };

type Status = { tone: "done" | "error"; text: string };

function asFile(file: ExportFile) {
  return typeof File === "function" ? new File([file.content], file.name, { type: file.mime }) : null;
}

function ExportDialog({ file, format, onClose }: { file: ExportFile | null; format: ExportFormat | null; onClose: () => void }) {
  const [status, setStatus] = useState<Status | null>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const shared = file ? asFile(file) : null;
  const shareMode = file ? chooseShareMode(navigator, shared) : "none";
  const label = format ? exportLabels[format] : "";

  const close = () => {
    setStatus(null);
    onClose();
  };

  const copy = async () => {
    if (!file) return;
    const copied = await copyText(file.content, textRef.current);
    setStatus(copied
      ? { tone: "done", text: "Текст скопирован." }
      : { tone: "error", text: "Не получилось скопировать. Текст выделен, скопируйте его вручную." });
  };

  const share = async () => {
    if (!file) return;
    try {
      if (shareMode === "file" && shared) await navigator.share({ files: [shared], title: file.name });
      else await navigator.share({ title: file.name, text: file.content });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setStatus({ tone: "error", text: "Не получилось поделиться. Скопируйте текст." });
    }
  };

  return (
    <Dialog
      open={file !== null}
      onClose={close}
      title={label}
      className="local-export-dialog"
      actions={file && (
        <>
          <Button variant="ghost" onClick={close}>Закрыть</Button>
          {shareMode !== "none" && <Button variant="secondary" onClick={() => void share()}>Поделиться</Button>}
          <Button onClick={() => void copy()}>Скопировать</Button>
        </>
      )}
    >
      {file && (
        <div className="local-export-dialog__body">
          <p>В Telegram файл {file.name} не скачивается. Скопируйте текст или поделитесь им.</p>
          <textarea
            ref={textRef}
            className="local-export-dialog__text"
            readOnly
            value={file.content}
            aria-label={`Текст ${label}`}
            rows={10}
          />
          {status && (
            <p className={`local-export-dialog__status local-export-dialog__status--${status.tone}`} role={status.tone === "error" ? "alert" : "status"}>
              {status.text}
            </p>
          )}
        </div>
      )}
    </Dialog>
  );
}

export function useLocalExport() {
  const [opened, setOpened] = useState<{ file: ExportFile; format: ExportFormat } | null>(null);

  const deliver = (lecture: LocalLecture, format: ExportFormat) => {
    const file = buildExport(lecture, format);
    if (chooseLocalDelivery(Boolean(getWebApp())) === "download") saveFile(file);
    else setOpened({ file, format });
  };

  const dialog = <ExportDialog file={opened?.file ?? null} format={opened?.format ?? null} onClose={() => setOpened(null)} />;

  return { deliver, dialog };
}
