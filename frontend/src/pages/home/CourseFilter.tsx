import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { CreateCourseDialog } from "../course/CreateCourseDialog";
import type { Course } from "./queries";

type CourseFilterProps = {
  courses: Course[] | undefined;
  selected: string | null;
  failed: boolean;
  onRetry: () => void;
};

export function CourseFilter({ courses, selected, failed, onRetry }: CourseFilterProps) {
  const listRef = useRef<HTMLUListElement>(null);
  const [creating, setCreating] = useState(false);

  const hasList = courses !== undefined && courses.length > 0;

  useEffect(() => {
    listRef.current?.querySelector('[aria-current="page"]')?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [selected, hasList]);

  return (
    <nav className="course-filter" aria-labelledby="course-filter-title">
      <h2 id="course-filter-title" className="course-filter__title">
        Курсы
      </h2>
      {courses === undefined && !failed && (
        <ul className="course-filter__list" aria-busy="true" aria-label="Загружаем курсы">
          {[0, 1, 2].map((index) => (
            <li key={index} className="course-filter__placeholder">
              <span className="skeleton skeleton--course" />
            </li>
          ))}
        </ul>
      )}
      {hasList && (
        <ul ref={listRef} className="course-filter__list">
          <li>
            <Link to="/" className="course-filter__item" aria-current={selected === null ? "page" : undefined}>
              <span className="course-filter__name">Все лекции</span>
            </Link>
          </li>
          {courses?.map((course) => (
            <li key={course.id}>
              <Link
                to={`/?course=${course.id}`}
                className="course-filter__item"
                aria-current={selected === course.id ? "page" : undefined}
              >
                <span className="course-filter__name">{course.title}</span>
                <span className="course-filter__count">{course.lecture_count}</span>
              </Link>
            </li>
          ))}
          <li>
            <button type="button" className="course-filter__item course-filter__new" onClick={() => setCreating(true)}>
              Новый курс
            </button>
          </li>
        </ul>
      )}
      {failed && (
        <p className="course-filter__note">
          Курсы не загрузились.{" "}
          <button type="button" className="home__text-action" onClick={onRetry}>
            Повторить
          </button>
        </p>
      )}
      {courses?.length === 0 && (
        <p className="course-filter__note">
          Курсов пока нет. Курс собирает лекции одного предмета в папку.{" "}
          <button type="button" className="home__text-action" onClick={() => setCreating(true)}>
            Создать курс
          </button>
        </p>
      )}
      {creating && <CreateCourseDialog onClose={() => setCreating(false)} />}
    </nav>
  );
}
