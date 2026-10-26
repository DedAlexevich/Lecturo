import { useState, type ReactNode } from "react";
import { Button } from "../../ui/Button";
import { Field } from "../../ui/Field";
import { Input } from "../../ui/Input";
import { linkErrorOf } from "./errors";

type LinkPanelProps = {
  courseField: ReactNode;
  pending: boolean;
  error: unknown;
  onSubmit: (url: string) => void;
  onClose: () => void;
};

function isWebLink(value: string) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:";
  } catch {
    return false;
  }
}

export function LinkPanel({ courseField, pending, error, onSubmit, onClose }: LinkPanelProps) {
  const [url, setUrl] = useState("");
  const [touched, setTouched] = useState(false);
  const trimmed = url.trim();
  const invalid = touched && !isWebLink(trimmed);

  return (
    <form
      className="add-lecture__form"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        setTouched(true);
        if (isWebLink(trimmed)) onSubmit(trimmed);
      }}
    >
      <Field
        label="Ссылка на видео"
        hint="VK Видео, YouTube, Rutube, Яндекс Диск и другие сайты с видео"
        error={invalid ? "Вставьте ссылку целиком, вместе с https://" : undefined}
      >
        {(control) => (
          <Input
            {...control}
            type="url"
            inputMode="url"
            autoComplete="off"
            placeholder="https://vkvideo.ru/video-…"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            onBlur={() => setTouched(trimmed !== "")}
          />
        )}
      </Field>
      {courseField}
      {error !== null && (
        <p className="add-lecture__error" role="alert">
          {linkErrorOf(error)}
        </p>
      )}
      <div className="dialog__actions">
        <Button variant="ghost" onClick={onClose}>
          Отмена
        </Button>
        <Button type="submit" loading={pending}>
          Добавить
        </Button>
      </div>
    </form>
  );
}
