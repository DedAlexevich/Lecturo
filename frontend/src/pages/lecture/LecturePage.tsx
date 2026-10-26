import { useEffect, useMemo } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router";
import type { components } from "../../api/schema";
import { ApiError } from "../../app/queryClient";
import { Button } from "../../ui/Button";
import { EmptyState } from "../../ui/EmptyState";
import { VideoPlayer } from "./players/VideoPlayer";
import { usePlayer } from "./players/player";
import { formatDuration, parseStartTime } from "./time";
import { Transcript } from "./Transcript";
import { useLecture } from "./useLecture";
import "./lecture.css";

type Lecture = components["schemas"]["LectureDetail"];

const dateFormat = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", year: "numeric" });

const pendingStatuses: Lecture["status"][] = ["queued", "waiting_quota", "processing"];

function BackLink() {
  return (
    <Link to="/" className="lecture__back">
      Все лекции
    </Link>
  );
}

function LectureMeta({ lecture }: { lecture: Lecture }) {
  const parts = [dateFormat.format(new Date(lecture.created_at))];
  if (lecture.duration_sec) parts.unshift(formatDuration(lecture.duration_sec));
  if (lecture.processed_locally) parts.push("обработано на устройстве");
  return <p className="lecture__meta">{parts.join(" · ")}</p>;
}

function NoVideo({ lecture }: { lecture: Lecture }) {
  const expiresAt = lecture.video_expires_at ? new Date(lecture.video_expires_at) : null;
  const external = lecture.embed_url !== null || lecture.source_url !== null;

  let title = "Видео недоступно";
  let description = "Расшифровка остаётся на странице.";
  if (pendingStatuses.includes(lecture.status) && !external) {
    title = "Видео ещё обрабатывается";
    description = "Плеер появится здесь, когда обработка закончится.";
  } else if (external) {
    title = "Видео на сайте источника";
    description = "Запись хранится на площадке, откуда её добавили.";
  } else if (expiresAt !== null && expiresAt < new Date()) {
    title = "Срок хранения видео истёк";
    description = `Видео удалено ${dateFormat.format(expiresAt)}. Расшифровка остаётся на странице.`;
  }

  return (
    <div className="lecture__no-video">
      <p className="lecture__no-video-title">{title}</p>
      <p className="lecture__no-video-text">{description}</p>
      {lecture.source_url && (
        <a href={lecture.source_url} target="_blank" rel="noreferrer" className="lecture__source">
          Открыть источник
        </a>
      )}
    </div>
  );
}

function TranscriptEmpty({ status }: { status: Lecture["status"] }) {
  if (pendingStatuses.includes(status)) {
    return (
      <p className="lecture__panel-note">
        Лекция ещё обрабатывается. Расшифровка появится здесь, когда обработка закончится.
      </p>
    );
  }
  if (status === "failed") {
    return <p className="lecture__panel-note">Обработка не удалась, поэтому расшифровки нет.</p>;
  }
  return <p className="lecture__panel-note">В записи не распознано ни одной фразы.</p>;
}

function LectureSkeleton() {
  return (
    <div className="lecture" aria-busy="true">
      <header className="lecture__header">
        <BackLink />
        <span className="lecture__bar lecture__bar--title" />
        <span className="lecture__bar lecture__bar--meta" />
      </header>
      <div className="lecture__body">
        <div className="lecture__media">
          <div className="lecture__bar lecture__bar--video" />
        </div>
        <section className="lecture__panel" aria-label="Расшифровка загружается">
          <h2 className="lecture__panel-title">Расшифровка</h2>
          <div className="lecture__skeleton-rows">
            {Array.from({ length: 7 }, (_, index) => (
              <span key={index} className="lecture__bar lecture__bar--row" />
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

function LectureError({ error, onRetry, retrying }: { error: Error; onRetry: () => void; retrying: boolean }) {
  const missing = error instanceof ApiError && (error.status === 404 || error.status === 422);
  if (missing) {
    return (
      <div className="lecture">
        <EmptyState
          title="Лекция не найдена"
          description="Возможно, её удалили или ссылка открыта не из того аккаунта."
          action={<Link to="/">К списку лекций</Link>}
        />
      </div>
    );
  }
  return (
    <div className="lecture">
      <header className="lecture__header">
        <BackLink />
      </header>
      <div className="lecture__error" role="alert">
        <p>Не удалось загрузить лекцию. Проверьте соединение и попробуйте ещё раз.</p>
        <Button variant="secondary" size="sm" onClick={onRetry} loading={retrying}>
          Повторить
        </Button>
      </div>
    </div>
  );
}

export function LecturePage() {
  const { id = "" } = useParams();
  const [searchParams] = useSearchParams();
  const { key: locationKey } = useLocation();
  const startAt = parseStartTime(searchParams.get("t"));
  const lecture = useLecture(id);
  const { currentTime, seek, playFrom, bind } = usePlayer();

  const rawSegments = lecture.data?.segments;
  const segments = useMemo(
    () => (rawSegments ? [...rawSegments].sort((a, b) => a.start - b.start) : []),
    [rawSegments],
  );

  useEffect(() => {
    if (startAt !== null) seek(startAt);
  }, [startAt, locationKey, seek]);

  if (lecture.isPending) return <LectureSkeleton />;
  if (lecture.isError) {
    return <LectureError error={lecture.error} onRetry={() => void lecture.refetch()} retrying={lecture.isFetching} />;
  }

  const data = lecture.data;
  const videoUrl = data.video_url ?? null;

  return (
    <div className="lecture">
      <header className="lecture__header">
        <BackLink />
        <h1 className="lecture__title">{data.title}</h1>
        <LectureMeta lecture={data} />
      </header>
      <div className="lecture__body">
        <div className="lecture__media">
          {videoUrl ? (
            <VideoPlayer key={videoUrl} src={videoUrl} title={data.title} {...bind} />
          ) : (
            <NoVideo lecture={data} />
          )}
        </div>
        <section
          className={segments.length > 0 ? "lecture__panel" : "lecture__panel lecture__panel--empty"}
          aria-labelledby="lecture-transcript"
        >
          <h2 id="lecture-transcript" className="lecture__panel-title">
            Расшифровка
          </h2>
          {segments.length > 0 ? (
            <Transcript
              segments={segments}
              currentTime={videoUrl ? currentTime : null}
              onSelect={videoUrl ? playFrom : undefined}
            />
          ) : (
            <TranscriptEmpty status={data.status} />
          )}
        </section>
      </div>
    </div>
  );
}
