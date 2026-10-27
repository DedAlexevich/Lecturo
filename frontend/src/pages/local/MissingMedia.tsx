import { useRef } from "react";
import { Button } from "../../ui/Button";

type MissingMediaProps = {
  disabled: boolean;
  onPick: (file: File) => void;
};

export function MissingMedia({ disabled, onPick }: MissingMediaProps) {
  const input = useRef<HTMLInputElement>(null);

  return (
    <div className="local-source local-source--notice local-media-missing" role="status">
      <p className="local-source__title">Записи нет в этом браузере</p>
      <p>Файл не поместился в хранилище или был удалён. Выберите его заново, и он будет открываться вместе с расшифровкой.</p>
      <input
        ref={input}
        type="file"
        accept="audio/*,video/*"
        hidden
        onChange={(event) => {
          const next = event.target.files?.[0];
          event.target.value = "";
          if (next) onPick(next);
        }}
      />
      <Button variant="secondary" size="sm" className="local-media-missing__pick" disabled={disabled} onClick={() => input.current?.click()}>
        Выбрать файл заново
      </Button>
    </div>
  );
}
