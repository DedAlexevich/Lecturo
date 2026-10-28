import { Link } from "react-router";
import { formatDuration } from "../../lib/duration";
import { formatDate, statusLabels } from "../home/format";
import type { Lecture } from "../home/queries";

type CourseLectureListProps = {
  lectures: Lecture[];
  removingId?: string;
  onRemove: (lecture: Lecture) => void;
};

export function CourseLectureList({ lectures, removingId, onRemove }: CourseLectureListProps) {
  return (
    <ul className="course-lectures">
      {lectures.map((lecture) => (
        <li key={lecture.id} className="course-lecture">
          <div className="course-lecture__main">
            <Link to={`/lectures/${lecture.id}`} className="course-lecture__title">
              {lecture.title}
            </Link>
            <p className="course-lecture__meta">
              <span className="course-lecture__duration">{formatDuration(lecture.duration_sec)}</span>
              <span>{formatDate(lecture.created_at)}</span>
              {lecture.status !== "ready" && (
                <span className={`course-lecture__status course-lecture__status--${lecture.status}`}>
                  {statusLabels[lecture.status]}
                </span>
              )}
            </p>
          </div>
          <button
            type="button"
            className="course-lecture__remove"
            disabled={removingId !== undefined}
            aria-busy={removingId === lecture.id || undefined}
            aria-label={`Убрать «${lecture.title}» из курса`}
            onClick={() => onRemove(lecture)}
          >
            {removingId === lecture.id ? "Убираем" : "Убрать"}
          </button>
        </li>
      ))}
    </ul>
  );
}

export function CourseLectureListSkeleton() {
  return (
    <ul className="course-lectures" aria-busy="true" aria-label="Загружаем лекции курса">
      {[0, 1, 2].map((index) => (
        <li key={index} className="course-lecture">
          <div className="course-lecture__main">
            <span className="course-skeleton course-skeleton--row" />
            <span className="course-skeleton course-skeleton--meta" />
          </div>
        </li>
      ))}
    </ul>
  );
}
