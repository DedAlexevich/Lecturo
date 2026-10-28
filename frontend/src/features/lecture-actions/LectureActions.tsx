import { useEffect, useId, useLayoutEffect, useRef, useState, type FormEvent } from "react";
import { Button } from "../../ui/Button";
import { Dialog } from "../../ui/Dialog";
import { Field } from "../../ui/Field";
import { Input } from "../../ui/Input";
import { ApiError } from "../../app/queryClient";
import { detailOf } from "../../api/errors";
import { CoursesDialog } from "./CoursesDialog";
import { placeMenu } from "./placement";
import { useDeleteLecture, useRegenerateSummary, useRenameLecture } from "./queries";
import "./lecture-actions.css";

function regenerateMessage(error: Error) {
  if (error instanceof ApiError) {
    const detail = detailOf(error.body);
    if (typeof detail === "string") return detail;
  }
  return "Не удалось запустить пересоздание. Попробуйте ещё раз.";
}

type LectureActionsProps = {
  lecture: { id: string; title: string; status: string };
  onDeleted?: () => void;
};

export function LectureActions({ lecture, onDeleted }: LectureActionsProps) {
  const trigger = useRef<HTMLButtonElement>(null);
  const container = useRef<HTMLDivElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const panelId = useId();
  const formId = useId();
  const [expanded, setExpanded] = useState(false);
  const [action, setAction] = useState<"rename" | "courses" | "delete" | "regenerate" | null>(null);
  const [title, setTitle] = useState(lecture.title);
  const [touched, setTouched] = useState(false);
  const rename = useRenameLecture(lecture.id);
  const remove = useDeleteLecture(lecture.id, () => {
    setAction(null);
    onDeleted?.();
  });
  const regenerate = useRegenerateSummary(lecture.id);
  const pending = rename.isPending || remove.isPending || regenerate.isPending;
  const titleError = touched && title.trim() === "" ? "Введите название лекции" : undefined;

  useEffect(() => {
    if (!expanded) return;
    function outside(event: PointerEvent) {
      if (!container.current?.contains(event.target as Node)) setExpanded(false);
    }
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [expanded]);

  useLayoutEffect(() => {
    if (!expanded) return;
    function place() {
      const menu = panel.current;
      const button = trigger.current;
      if (!menu || !button) return;
      menu.style.left = "";
      menu.style.width = "";
      const placement = placeMenu(
        button.getBoundingClientRect(),
        menu.offsetWidth,
        document.documentElement.clientWidth,
      );
      menu.style.left = `${placement.left}px`;
      if (placement.width !== undefined) menu.style.width = `${placement.width}px`;
    }
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [expanded, lecture.status]);

  function open(next: "rename" | "courses" | "delete" | "regenerate") {
    setExpanded(false);
    trigger.current?.focus();
    setTitle(lecture.title);
    setTouched(false);
    rename.reset();
    remove.reset();
    regenerate.reset();
    setAction(next);
  }

  function finishAction() {
    setAction(null);
    requestAnimationFrame(() => trigger.current?.focus());
  }

  function close() {
    if (!pending) finishAction();
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    setTouched(true);
    if (pending || title.trim() === "") return;
    rename.mutate(title.trim(), { onSuccess: finishAction });
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
        <div id={panelId} ref={panel} className="lecture-actions__panel">
          <Button variant="ghost" onClick={() => open("rename")}>Переименовать</Button>
          <Button variant="ghost" onClick={() => open("courses")}>В курс…</Button>
          {lecture.status === "ready" && (
            <Button variant="ghost" onClick={() => open("regenerate")}>Пересоздать главы и конспект</Button>
          )}
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
      {action === "courses" && <CoursesDialog lecture={lecture} onClose={finishAction} />}
      {action === "regenerate" && (
        <Dialog
          open
          dismissible={!pending}
          title="Пересоздать главы и конспект?"
          onClose={close}
          actions={
            <>
              <Button variant="secondary" autoFocus disabled={pending} onClick={close}>Отмена</Button>
              <Button
                loading={regenerate.isPending}
                onClick={() => {
                  if (!pending) regenerate.mutate(undefined, { onSuccess: finishAction });
                }}
              >
                Пересоздать
              </Button>
            </>
          }
        >
          <p className="lecture-actions__description">
            Текст лекции будет заново отправлен на обработку, и главы с конспектом заменятся новыми.
            Расшифровка не изменится. Если что-то пойдёт не так, останутся прежние главы и конспект.
            Повторно пересоздать можно не раньше чем через 5 минут.
          </p>
          {regenerate.isError && (
            <p role="alert" className="lecture-actions__error">
              {regenerateMessage(regenerate.error)}
            </p>
          )}
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
