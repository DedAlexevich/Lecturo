import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { Button } from "../../ui/Button";
import { Dialog } from "../../ui/Dialog";
import { Field } from "../../ui/Field";
import { Input } from "../../ui/Input";
import { useDeleteLecture, useRenameLecture } from "./queries";
import "./lecture-actions.css";

type LectureActionsProps = {
  lecture: { id: string; title: string };
};

export function LectureActions({ lecture }: LectureActionsProps) {
  const navigate = useNavigate();
  const trigger = useRef<HTMLButtonElement>(null);
  const container = useRef<HTMLDivElement>(null);
  const panelId = useId();
  const formId = useId();
  const [expanded, setExpanded] = useState(false);
  const [action, setAction] = useState<"rename" | "delete" | null>(null);
  const [title, setTitle] = useState(lecture.title);
  const [touched, setTouched] = useState(false);
  const rename = useRenameLecture(lecture.id);
  const remove = useDeleteLecture(lecture.id, () => navigate("/", { replace: true }));
  const pending = rename.isPending || remove.isPending;
  const titleError = touched && title.trim() === "" ? "Введите название лекции" : undefined;

  useEffect(() => {
    if (!expanded) return;
    function outside(event: PointerEvent) {
      if (!container.current?.contains(event.target as Node)) setExpanded(false);
    }
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [expanded]);

  function open(next: "rename" | "delete") {
    setExpanded(false);
    trigger.current?.focus();
    setTitle(lecture.title);
    setTouched(false);
    rename.reset();
    remove.reset();
    setAction(next);
  }

  function finishRename() {
    setAction(null);
    requestAnimationFrame(() => trigger.current?.focus());
  }

  function close() {
    if (!pending) finishRename();
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    setTouched(true);
    if (pending || title.trim() === "") return;
    rename.mutate(title.trim(), { onSuccess: finishRename });
  }

  return (
    <div
      className="lecture-actions"
      ref={container}
      onKeyDown={(event) => {
        if (event.key === "Escape" && expanded) {
          event.stopPropagation();
          setExpanded(false);
          trigger.current?.focus();
        }
      }}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setExpanded(false);
      }}
    >
      <Button
        ref={trigger}
        variant="ghost"
        size="sm"
        className="lecture-actions__trigger"
        aria-label={`Действия с лекцией «${lecture.title}»`}
        aria-expanded={expanded}
        aria-controls={panelId}
        onClick={() => setExpanded(!expanded)}
      >
        <svg width="18" height="18" viewBox="0 0 18 18" fill="currentColor" aria-hidden="true">
          <circle cx="9" cy="3" r="1.5" />
          <circle cx="9" cy="9" r="1.5" />
          <circle cx="9" cy="15" r="1.5" />
        </svg>
      </Button>
      {expanded && (
        <div id={panelId} className="lecture-actions__panel">
          <Button variant="ghost" onClick={() => open("rename")}>Переименовать</Button>
          <Button variant="ghost" className="lecture-actions__delete" onClick={() => open("delete")}>
            Удалить
          </Button>
        </div>
      )}
      {action === "rename" && (
        <Dialog
          open
          dismissible={!pending}
          title="Переименовать лекцию"
          onClose={close}
          actions={
            <>
              <Button variant="secondary" disabled={pending} onClick={close}>Отмена</Button>
              <Button type="submit" form={formId} loading={rename.isPending}>Сохранить</Button>
            </>
          }
        >
          <form id={formId} className="lecture-actions__form" onSubmit={submit} noValidate>
            <Field label="Название" error={titleError}>
              {(control) => (
                <Input
                  {...control}
                  autoFocus
                  value={title}
                  maxLength={300}
                  autoComplete="off"
                  disabled={pending}
                  onChange={(event) => setTitle(event.target.value)}
                />
              )}
            </Field>
            {rename.isError && (
              <p role="alert" className="lecture-actions__error">
                Не удалось переименовать лекцию. Попробуйте ещё раз.
              </p>
            )}
          </form>
        </Dialog>
      )}
      {action === "delete" && (
        <Dialog
          open
          dismissible={!pending}
          title="Удалить лекцию?"
          onClose={close}
          actions={
            <>
              <Button variant="secondary" autoFocus disabled={pending} onClick={close}>Отмена</Button>
              <Button variant="danger" loading={remove.isPending} onClick={() => {
                if (!pending) remove.mutate();
              }}>
                Удалить лекцию
              </Button>
            </>
          }
        >
          <p className="lecture-actions__description">
            Лекция «{lecture.title}» и её материалы будут удалены из кабинета и всех курсов.
            Восстановить их не получится.
          </p>
          {remove.isError && (
            <p role="alert" className="lecture-actions__error">
              Не удалось удалить лекцию. Попробуйте ещё раз.
            </p>
          )}
        </Dialog>
      )}
    </div>
  );
}
