import { useId, useState, type FormEvent } from "react";
import { useCourses } from "../../pages/home/queries";
import { Button } from "../../ui/Button";
import { Checkbox } from "../../ui/Checkbox";
import { Dialog } from "../../ui/Dialog";
import { Field } from "../../ui/Field";
import { Input } from "../../ui/Input";
import { Spinner } from "../../ui/Spinner";
import { useChangeLectureCourses, useLectureCourses } from "./queries";

type CoursesDialogProps = {
  lecture: { id: string; title: string };
  onClose: () => void;
};

export function CoursesDialog({ lecture, onClose }: CoursesDialogProps) {
  const formId = useId();
  const courses = useCourses();
  const current = useLectureCourses(lecture.id, true);
  const change = useChangeLectureCourses(lecture.id);
  const [picked, setPicked] = useState<Set<string> | null>(null);
  const [newCourse, setNewCourse] = useState("");
  const pending = change.isPending;
  const currentIds = new Set(current.data?.map((course) => course.id));
  const selected = picked ?? currentIds;
  const loading = courses.isPending || current.isPending;
  const failed = courses.isError || current.isError;
  const ready = !loading && !failed;

  function close() {
    if (!pending) onClose();
  }

  function toggle(courseId: string, checked: boolean) {
    const next = new Set(selected);
    if (checked) next.add(courseId);
    else next.delete(courseId);
    setPicked(next);
  }

  function save(target: Set<string>, title: string) {
    change.mutate(
      {
        add: [...target].filter((id) => !currentIds.has(id)),
        remove: [...currentIds].filter((id) => !target.has(id)),
        newCourse: title || undefined,
      },
      { onSuccess: onClose },
    );
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (pending || !ready) return;
    save(selected, newCourse.trim());
  }

  function retry() {
    if (courses.isError) void courses.refetch();
    if (current.isError) void current.refetch();
  }

  return (
    <Dialog
      open
      dismissible={!pending}
      title="Лекция в курсах"
      onClose={close}
      actions={
        <>
          {ready && currentIds.size > 0 && (
            <Button
              variant="ghost"
              className="lecture-courses__remove"
              disabled={pending}
              onClick={() => save(new Set(), "")}
            >
              {currentIds.size > 1 ? "Убрать из курсов" : "Убрать из курса"}
            </Button>
          )}
          <Button variant="secondary" disabled={pending} onClick={close}>
            Отмена
          </Button>
          <Button type="submit" form={formId} loading={pending} disabled={!ready}>
            Сохранить
          </Button>
        </>
      }
    >
      <form id={formId} className="lecture-courses" onSubmit={submit} noValidate>
        <p className="lecture-actions__description">«{lecture.title}»</p>
        {loading && !failed && (
          <div className="lecture-courses__state">
            <Spinner size="sm" label="Загружаем курсы" />
          </div>
        )}
        {failed && (
          <p className="lecture-courses__state" role="alert">
            Курсы не загрузились.{" "}
            <Button variant="ghost" size="sm" onClick={retry}>
              Повторить
            </Button>
          </p>
        )}
        {ready && courses.data.length > 0 && (
          <fieldset className="lecture-courses__list" disabled={pending}>
            <legend className="lecture-courses__legend">Курсы</legend>
            {courses.data.map((course) => (
              <Checkbox
                key={course.id}
                label={course.title}
                checked={selected.has(course.id)}
                onChange={(event) => toggle(course.id, event.target.checked)}
              />
            ))}
          </fieldset>
        )}
        {ready && courses.data.length === 0 && (
          <p className="lecture-courses__state">Курсов пока нет. Создайте первый, и лекция попадёт в него.</p>
        )}
        {ready && (
          <Field label="Новый курс" hint="Необязательно: создадим курс и добавим в него лекцию">
            {(control) => (
              <Input
                {...control}
                value={newCourse}
                maxLength={200}
                autoComplete="off"
                autoFocus={courses.data.length === 0}
                disabled={pending}
                placeholder="Например, Матанализ, 2 семестр"
                onChange={(event) => setNewCourse(event.target.value)}
              />
            )}
          </Field>
        )}
        {change.isError && (
          <p role="alert" className="lecture-actions__error">
            Не удалось сохранить. Попробуйте ещё раз.
          </p>
        )}
      </form>
    </Dialog>
  );
}
