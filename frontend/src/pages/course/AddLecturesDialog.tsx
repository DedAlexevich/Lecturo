import { useId, useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { Button } from "../../ui/Button";
import { Checkbox } from "../../ui/Checkbox";
import { Dialog } from "../../ui/Dialog";
import { Input } from "../../ui/Input";
import { Spinner } from "../../ui/Spinner";
import { formatDate, formatDuration } from "../home/format";
import { useLectures, type Lecture } from "../home/queries";

const searchThreshold = 6;

type AddLecturesDialogProps = {
  courseTitle: string;
  inCourse: Lecture[];
  pending: boolean;
  failed: boolean;
  onSubmit: (lectureIds: string[]) => void;
  onClose: () => void;
};

export function AddLecturesDialog({ courseTitle, inCourse, pending, failed, onSubmit, onClose }: AddLecturesDialogProps) {
  const formId = useId();
  const lectures = useLectures(null);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const available = useMemo(() => {
    const taken = new Set(inCourse.map((lecture) => lecture.id));
    return lectures.data?.filter((lecture) => !taken.has(lecture.id)) ?? [];
  }, [lectures.data, inCourse]);

  const needle = query.trim().toLocaleLowerCase("ru");
  const shown = needle ? available.filter((lecture) => lecture.title.toLocaleLowerCase("ru").includes(needle)) : available;

  function toggle(lectureId: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(lectureId)) next.delete(lectureId);
      else next.add(lectureId);
      return next;
    });
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (selected.size === 0) return;
    onSubmit(available.filter((lecture) => selected.has(lecture.id)).map((lecture) => lecture.id));
  }

  let body;
  if (lectures.isPending) {
    body = (
      <div className="pick-lectures__state">
        <Spinner label="Загружаем лекции" />
      </div>
    );
  } else if (lectures.isError) {
    body = (
      <p className="pick-lectures__state" role="alert">
        Не получилось загрузить лекции.{" "}
        <button type="button" className="course__text-action" onClick={() => lectures.refetch()}>
          Повторить
        </button>
      </p>
    );
  } else if (lectures.data.length === 0) {
    body = (
      <p className="pick-lectures__state">
        У вас пока нет лекций. <Link to="/?add=lecture">Добавить лекцию</Link>
      </p>
    );
  } else if (available.length === 0) {
    body = <p className="pick-lectures__state">Все ваши лекции уже в этом курсе.</p>;
  } else {
    body = (
      <>
        {available.length > searchThreshold && (
          <Input
            type="search"
            value={query}
            aria-label="Найти лекцию по названию"
            placeholder="Найти по названию"
            onChange={(event) => setQuery(event.target.value)}
          />
        )}
        {shown.length === 0 ? (
          <p className="pick-lectures__state">Ничего не нашлось.</p>
        ) : (
          <ul className="pick-lectures__list" aria-label="Лекции не из этого курса">
            {shown.map((lecture) => (
              <li key={lecture.id} className="pick-lectures__item">
                <Checkbox
                  checked={selected.has(lecture.id)}
                  onChange={() => toggle(lecture.id)}
                  label={
                    <span className="pick-lectures__label">
                      <span className="pick-lectures__title">{lecture.title}</span>
                      <span className="pick-lectures__meta">
                        {formatDuration(lecture.duration_sec)} · {formatDate(lecture.created_at)}
                      </span>
                    </span>
                  }
                />
              </li>
            ))}
          </ul>
        )}
      </>
    );
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title={`Добавить в «${courseTitle}»`}
      actions={
        <>
          <Button variant="secondary" onClick={onClose}>
            Отмена
          </Button>
          <Button type="submit" form={formId} loading={pending} disabled={selected.size === 0}>
            {selected.size > 0 ? `Добавить (${selected.size})` : "Добавить"}
          </Button>
        </>
      }
    >
      <form id={formId} className="pick-lectures" onSubmit={submit}>
        {body}
        {failed && (
          <p className="course-form__error" role="alert">
            Не получилось добавить лекции. Попробуйте ещё раз.
          </p>
        )}
      </form>
    </Dialog>
  );
}
