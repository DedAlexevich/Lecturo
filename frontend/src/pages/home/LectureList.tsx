import { LectureActions } from "../../features/lecture-actions/LectureActions";
import { Link } from "react-router";
import { Progress } from "../../ui/Progress";
import { formatDate, formatDuration, runningStep, statusLabels } from "./format";
import { useProgress, type Lecture, type LectureProgress } from "./queries";

const sourceLabels: Record<Lecture["source_type"], string> = {
  upload: "Файл",
  link: "Ссылка",
  local: "На устройстве",
};

function LectureStatusMark({ lecture, progress }: { lecture: Lecture; progress?: LectureProgress }) {
  const position = lecture.status === "queued" ? progress?.queue_position : null;
  return (
    <span className={`lecture-status lecture-status--${lecture.status}`}>
      {statusLabels[lecture.status]}
      {position ? `: ${position}` : ""}
    </span>
  );
}

function LectureRow({ lecture, progress }: { lecture: Lecture; progress?: LectureProgress }) {
  const step = lecture.status === "processing" ? runningStep(progress) : null;

  return (
    <li className="lecture-row">
      <div className="lecture-row__main">
        <Link to={`/lectures/${lecture.id}`} className="lecture-row__title">
          {lecture.title}
        </Link>
        <p className="lecture-row__meta">
          <span className="lecture-row__duration">{formatDuration(lecture.duration_sec)}</span>
          <span>{sourceLabels[lecture.source_type]}</span>
          <span>{formatDate(lecture.created_at)}</span>
        </p>
        {step && (
          <div className="lecture-row__progress">
            <Progress label={step.label} value={step.value} />
          </div>
        )}
      </div>
      <div className="lecture-row__aside">
        <LectureStatusMark lecture={lecture} progress={progress} />
        <LectureActions lecture={lecture} />
      </div>
    </li>
  );
}

export function LectureList({ lectures }: { lectures: Lecture[] }) {
  const progress = useProgress(lectures);

  return (
    <ul className="lecture-list">
      {lectures.map((lecture) => (
        <LectureRow key={lecture.id} lecture={lecture} progress={progress.get(lecture.id)} />
      ))}
    </ul>
  );
}

export function LectureListSkeleton() {
  return (
    <ul className="lecture-list" aria-busy="true" aria-label="Загружаем лекции">
      {[0, 1, 2, 3].map((index) => (
        <li key={index} className="lecture-row">
          <div className="lecture-row__main">
            <span className="skeleton skeleton--title" />
            <span className="skeleton skeleton--meta" />
          </div>
        </li>
      ))}
    </ul>
  );
}
