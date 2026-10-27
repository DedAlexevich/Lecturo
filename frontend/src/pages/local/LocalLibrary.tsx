import { useCallback, useEffect, useState } from "react";
import { downloadLecture } from "../../local/export";
import type { ExportFormat } from "../../local/export";
import { deleteLocalLecture, getLocalLecture, listLocalLectures } from "../../local/storage";
import type { LocalLecture, LocalLectureSummary } from "../../local/storage";
import { formatTimecode } from "../../lib/timecode";
import { Button } from "../../ui/Button";

const formats: { id: ExportFormat; label: string }[] = [
  { id: "srt", label: "SRT" },
  { id: "vtt", label: "VTT" },
  { id: "md", label: "MD" },
];

const dateFormat = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });

type LocalLibraryProps = {
  disabled: boolean;
  version: number;
  activeId?: string;
  onOpen: (lecture: LocalLecture) => void;
  onRemoved: (id: string) => void;
};

export function LocalLibrary({ disabled, version, activeId, onOpen, onRemoved }: LocalLibraryProps) {
  const [items, setItems] = useState<LocalLectureSummary[] | null>(null);
  const [failed, setFailed] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setItems(await listLocalLectures());
      setFailed(false);
    } catch {
      setItems([]);
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh, version]);

  async function withLecture(id: string, action: (lecture: LocalLecture) => void) {
    try {
      const lecture = await getLocalLecture(id);
      if (lecture) action(lecture);
      else await refresh();
    } catch {
      setFailed(true);
    }
  }

  async function remove(item: LocalLectureSummary) {
    if (!window.confirm(`Удалить «${item.title}» с этого устройства?`)) return;
    try {
      await deleteLocalLecture(item.id);
      onRemoved(item.id);
      await refresh();
    } catch {
      setFailed(true);
    }
  }

  if (items === null || (items.length === 0 && !failed)) return null;

  return (
    <section className="local-library" aria-labelledby="local-library-title">
      <h2 id="local-library-title">Сохранённые на устройстве</h2>
      {failed && <p className="local-error" role="alert">Не удалось прочитать хранилище браузера.</p>}
      <ul className="local-library__list">
        {items.map((item) => (
          <li key={item.id} className={`local-library__item${item.id === activeId ? " local-library__item--active" : ""}`}>
            <div className="local-library__info">
              <strong>{item.title}</strong>
              <span>{dateFormat.format(item.createdAt)} · {formatTimecode(item.durationSec)}</span>
            </div>
            <div className="local-library__actions">
              <Button disabled={disabled} size="sm" variant="secondary" onClick={() => void withLecture(item.id, onOpen)}>Открыть</Button>
              {formats.map((format) => (
                <Button key={format.id} disabled={disabled} size="sm" variant="ghost" aria-label={`Скачать «${item.title}» в формате ${format.label}`} onClick={() => void withLecture(item.id, (lecture) => downloadLecture(lecture, format.id))}>{format.label}</Button>
              ))}
              <Button disabled={disabled} size="sm" variant="ghost" aria-label={`Удалить «${item.title}»`} onClick={() => void remove(item)}>Удалить</Button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
