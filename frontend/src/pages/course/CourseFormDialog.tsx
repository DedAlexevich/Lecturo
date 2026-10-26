import { useId, useState, type FormEvent } from "react";
import { Button } from "../../ui/Button";
import { Dialog } from "../../ui/Dialog";
import { Field } from "../../ui/Field";
import { Input } from "../../ui/Input";
import type { CourseFields } from "./queries";

const titleLimit = 200;

type CourseFormDialogProps = {
  title: string;
  submitLabel: string;
  initial?: CourseFields;
  pending: boolean;
  failed: boolean;
  onSubmit: (fields: CourseFields) => void;
  onClose: () => void;
};

export function CourseFormDialog({
  title,
  submitLabel,
  initial,
  pending,
  failed,
  onSubmit,
  onClose,
}: CourseFormDialogProps) {
  const formId = useId();
  const [name, setName] = useState(initial?.title ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [touched, setTouched] = useState(false);
  const nameError = touched && name.trim() === "" ? "Введите название курса" : undefined;

  function submit(event: FormEvent) {
    event.preventDefault();
    setTouched(true);
    if (name.trim() === "") return;
    onSubmit({ title: name.trim(), description: description.trim() });
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title={title}
      actions={
        <>
          <Button variant="secondary" onClick={onClose}>
            Отмена
          </Button>
          <Button type="submit" form={formId} loading={pending}>
            {submitLabel}
          </Button>
        </>
      }
    >
      <form id={formId} className="course-form" onSubmit={submit} noValidate>
        <Field label="Название" error={nameError}>
          {(control) => (
            <Input
              {...control}
              value={name}
              maxLength={titleLimit}
              autoFocus
              autoComplete="off"
              placeholder="Например, Матанализ, 2 семестр"
              onChange={(event) => setName(event.target.value)}
            />
          )}
        </Field>
        <Field label="Описание" hint="Необязательно: преподаватель, группа, расписание">
          {(control) => (
            <Input
              {...control}
              value={description}
              autoComplete="off"
              onChange={(event) => setDescription(event.target.value)}
            />
          )}
        </Field>
        {failed && (
          <p className="course-form__error" role="alert">
            Не получилось сохранить курс. Попробуйте ещё раз.
          </p>
        )}
      </form>
    </Dialog>
  );
}
