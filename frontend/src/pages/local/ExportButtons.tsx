import type { ExportFormat } from "../../local/export";
import type { LocalLecture } from "../../local/storage";
import { Button } from "../../ui/Button";
import { exportLabels, useLocalExport } from "./ExportDialog";

const formats: ExportFormat[] = ["srt", "vtt", "md"];

type ExportButtonsProps = {
  lecture: LocalLecture;
};

export function ExportButtons({ lecture }: ExportButtonsProps) {
  const { deliver, dialog } = useLocalExport();

  return (
    <div className="local-export" role="group" aria-label="Скачать расшифровку">
      <span className="local-export__label">Скачать</span>
      {formats.map((format) => (
        <Button key={format} variant="secondary" size="sm" onClick={() => deliver(lecture, format)}>{exportLabels[format]}</Button>
      ))}
      {dialog}
    </div>
  );
}
