import { Link, useSearchParams } from "react-router";
import { GlobalSearch } from "../../features/search/GlobalSearch";
import { Button } from "../../ui/Button";
import { EmptyState } from "../../ui/EmptyState";
import { CourseFilter } from "./CourseFilter";
import { lecturesCount } from "./format";
import { LectureList, LectureListSkeleton } from "./LectureList";
import { ApiError } from "../../app/queryClient";
import { isActive, useCourses, useLectures, type Lecture } from "./queries";
import "./home.css";

function summaryOf(lectures: Lecture[]) {
  const active = lectures.filter((lecture) => isActive(lecture.status)).length;
  const failed = lectures.filter((lecture) => lecture.status === "failed").length;
  const parts = [lecturesCount(lectures.length)];
  if (active > 0) parts.push(`в работе ${active}`);
  if (failed > 0) parts.push(`с ошибкой ${failed}`);
  return parts.join(" · ");
}

export function HomePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const courseId = searchParams.get("course");
  const lectures = useLectures(courseId);
  const courses = useCourses();
  const course = courses.data?.find((item) => item.id === courseId);
  const courseMissing =
    courseId !== null &&
    lectures.error instanceof ApiError &&
    (lectures.error.status === 404 || lectures.error.status === 422);

  function openAddLecture() {
    setSearchParams((params) => {
      params.set("add", "lecture");
      return params;
    });
  }

  const noLectures = !courseId && lectures.data?.length === 0;
  const addButton = <Button onClick={openAddLecture}>Добавить лекцию</Button>;

  return (
    <div className="home">
      <header className="home__head">
        <div className="home__heading">
          <h1 className="home__title">{courseId ? (course?.title ?? "Курс") : "Лекции"}</h1>
          {lectures.data && lectures.data.length > 0 && <p className="home__summary">{summaryOf(lectures.data)}</p>}
        </div>
        <div className="home__actions">
          {courseId && !courseMissing && (
            <Link to={`/courses/${courseId}`} className="home__text-action">
              Открыть курс
            </Link>
          )}
          {!noLectures && addButton}
        </div>
      </header>

      <CourseFilter
        courses={courses.data}
        selected={courseId}
        failed={courses.isError}
        onRetry={() => courses.refetch()}
      />

      <section className="home__lectures" aria-label="Список лекций">
        {lectures.isPending && <LectureListSkeleton />}
        {courseMissing && <EmptyState title="Курс не найден" action={<Link to="/">Все лекции</Link>} />}
        {lectures.isError && !lectures.data && !courseMissing && (
          <div className="home__error" role="alert">
            <p>Не получилось загрузить лекции.</p>
            <button type="button" className="home__text-action" onClick={() => lectures.refetch()}>
              Повторить
            </button>
          </div>
        )}
        {lectures.data?.length === 0 &&
          (courseId ? (
            <EmptyState title="В этом курсе пока нет лекций" />
          ) : (
            <EmptyState
              title="Лекций пока нет"
              description="Загрузите запись занятия или вставьте ссылку на видео. Мы распознаем речь и соберём конспект с главами."
              action={addButton}
            />
          ))}
        {lectures.data &&
          lectures.data.length > 0 &&
          (courseId ? (
            <LectureList lectures={lectures.data} />
          ) : (
            <GlobalSearch>
              <LectureList lectures={lectures.data} />
            </GlobalSearch>
          ))}
      </section>
    </div>
  );
}
