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

function withScheme(value: string) {
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(value)) return value;
  return `https://${value.replace(/^\/\//, "")}`;
}

function webLinkOf(value: string) {
  try {
    const url = new URL(withScheme(value));
    const web = url.protocol === "https:" || url.protocol === "http:";
    return web && url.hostname.includes(".") ? url.href : null;
  } catch {
    return null;
  }
}

export function LinkPanel({ courseField, pending, error, onSubmit, onClose }: LinkPanelProps) {
  const [url, setUrl] = useState("");
  const [touched, setTouched] = useState(false);
  const trimmed = url.trim();
  const link = webLinkOf(trimmed);
  const invalid = touched && link === null;

  return (
    <form
      className="add-lecture__form"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        setTouched(true);
        if (link !== null) onSubmit(link);
      }}
    >
      <Field
        label="Ссылка на видео"
        hint="VK Видео, YouTube, Rutube, Яндекс Диск и другие сайты с видео"
        error={invalid ? "Не похоже на ссылку. Пример: youtu.be/…" : undefined}
      >
        {(control) => (
          <Input
            {...control}
            type="text"
            inputMode="url"
            autoCapitalize="none"
            spellCheck={false}
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
