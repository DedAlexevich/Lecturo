import { Link } from "react-router";
import type { components } from "../../api/schema";
import { lecturesCount } from "../home/format";
import { formatDuration } from "../lecture/time";
import { LocalBadge } from "./LocalBadge";

type Course = components["schemas"]["PublicCourseOut"];

export function PublicCourse({ token, course }: { token: string; course: Course }) {
  return (
    <article className="public-course">
      <header className="public-course__head">
        <h1 className="public-course__title">{course.title}</h1>
        {course.description && <p className="public-course__description">{course.description}</p>}
        <div className="public__meta">
          <span>{lecturesCount(course.lectures.length)}</span>
          <span>Только чтение</span>
        </div>
      </header>
      {course.lectures.length === 0 ? (
        <p className="public-course__empty">В курсе пока нет готовых лекций.</p>
      ) : (
        <ol className="public-course__list">
          {course.lectures.map((lecture) => (
            <li key={lecture.id} className="public-course__item">
              <div className="public-course__name">
                <Link to={`/s/${token}/${lecture.id}`} className="public-course__link">
                  {lecture.title}
                </Link>
                <div className="public__meta">
                  {lecture.duration_sec !== null && <span>{formatDuration(lecture.duration_sec)}</span>}
                  {lecture.processed_locally && <LocalBadge />}
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}
    </article>
  );
}
