import { downloadLecture } from "../../local/export";
import type { ExportFormat } from "../../local/export";
import type { LocalLecture } from "../../local/storage";
import { Button } from "../../ui/Button";

const formats: { id: ExportFormat; label: string }[] = [
  { id: "srt", label: "SRT" },
  { id: "vtt", label: "VTT" },
  { id: "md", label: "Markdown" },
];

type ExportButtonsProps = {
  lecture: LocalLecture;
};

export function ExportButtons({ lecture }: ExportButtonsProps) {
  return (
    <div className="local-export" role="group" aria-label="Скачать расшифровку">
      <span className="local-export__label">Скачать</span>
      {formats.map((format) => (
        <Button key={format.id} variant="secondary" size="sm" onClick={() => downloadLecture(lecture, format.id)}>{format.label}</Button>
      ))}
    </div>
  );
}
