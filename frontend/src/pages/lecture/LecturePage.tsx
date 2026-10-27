import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router";
import type { components } from "../../api/schema";
import { ApiError } from "../../app/queryClient";
import { LectureActions } from "../../features/lecture-actions/LectureActions";
import { QuizButton } from "../../features/quiz/QuizButton";
import { SearchPanel } from "../../features/search/SearchPanel";
import { ShareButton } from "../../features/share/ShareButton";
import { Button } from "../../ui/Button";
import { EmptyState } from "../../ui/EmptyState";
import { Tabs } from "../../ui/Tabs";
import { Markdown } from "../legal/markdown";
import { Chapters } from "./Chapters";
import { ExportActions } from "./ExportActions";
import { EmbedPlayer } from "./players/EmbedPlayer";
import { resolveEmbed } from "./players/embed";
import { VideoPlayer } from "./players/VideoPlayer";
import { usePlayer, videoIdentity } from "./players/player";
import { Processing } from "./Processing";
import { formatDuration, parseSection, parseStartTime } from "./time";
import { Transcript } from "./Transcript";
import { fetchLecture, isPending, useLecture, useLectureStatus, useRetryProcessing } from "./useLecture";
import "./lecture.css";

type Lecture = components["schemas"]["LectureDetail"];

const dateFormat = new Intl.DateTimeFormat("ru-RU", {
  day: "numeric",
  month: "long",
  year: "numeric",
});

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
  if (isPending(lecture.status) && !external) {
    title = "Запись ещё обрабатывается";
    description = "Плеер появится здесь, когда обработка закончится.";
  } else if (external) {
    title = "Видео на сайте источника";
    description = "Запись хранится на площадке, откуда её добавили.";
  } else if (expiresAt !== null && expiresAt < new Date()) {
    title = "Срок хранения видео истёк";
    description = `Видео удалено ${dateFormat.format(expiresAt)}. Расшифровка остаётся на странице.`;
  } else if (lecture.audio_only || lecture.status === "failed") {
    title = "Запись недоступна";
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

type PanelKind = "summary" | "chapters" | "transcript";

const panelNotes: Record<PanelKind, { pending: string; failed: string; empty: string }> = {
  summary: {
    pending: "Конспект появится здесь, когда обработка закончится.",
    failed: "Обработка не удалась, поэтому конспекта нет.",
    empty: "Для этой лекции конспекта нет.",
  },
  chapters: {
    pending: "Главы появятся здесь, когда обработка закончится.",
    failed: "Обработка не удалась, поэтому глав нет.",
    empty: "Лекция слишком короткая, чтобы делить её на главы.",
  },
  transcript: {
    pending: "Расшифровка появится здесь, когда обработка закончится.",
    failed: "Обработка не удалась, поэтому расшифровки нет.",
    empty: "В записи не распознано ни одной фразы.",
  },
};

function PanelEmpty({ kind, status }: { kind: PanelKind; status: Lecture["status"] }) {
  const notes = panelNotes[kind];
  const note = isPending(status) ? notes.pending : status === "failed" ? notes.failed : notes.empty;
  return <p className="lecture__panel-note">{note}</p>;
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
        <section className="lecture__panel" aria-label="Материалы лекции загружаются">
          <div className="lecture__tabs-skeleton">
            <span className="lecture__bar lecture__bar--tab" />
            <span className="lecture__bar lecture__bar--tab" />
            <span className="lecture__bar lecture__bar--tab" />
          </div>
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
  const section = parseSection(searchParams.get("section"));
  const summaryRef = useRef<HTMLDivElement>(null);
  const shownSection = useRef<string | null>(null);
  const lecture = useLecture(id);
  const status = useLectureStatus(id, lecture.data);
  const retry = useRetryProcessing(id);
  const [tab, setTab] = useState<PanelKind>("summary");
  const [searching, setSearching] = useState(false);
  const [errorDismissed, setErrorDismissed] = useState(false);
  const { currentTime, seek, playFrom, bind } = usePlayer();

  const rawSegments = lecture.data?.segments;
  const segments = useMemo(
    () => (rawSegments ? [...rawSegments].sort((a, b) => a.start - b.start) : []),
    [rawSegments],
  );
  const rawChapters = lecture.data?.chapters;
  const chapters = useMemo(
    () => (rawChapters ? [...rawChapters].sort((a, b) => a.start - b.start) : []),
    [rawChapters],
  );

  useEffect(() => {
    if (startAt !== null) seek(startAt);
  }, [startAt, locationKey, seek]);

  useEffect(() => {
    if (section !== null) setTab("summary");
  }, [section, locationKey]);

  const summaryReady = Boolean(lecture.data?.summary?.content_md.trim());

  useEffect(() => {
    if (section === null || !summaryReady || tab !== "summary") return;
    if (shownSection.current === locationKey) return;
    const heading = summaryRef.current?.querySelectorAll("h2, h3, h4")[section];
    if (!(heading instanceof HTMLElement)) return;
    shownSection.current = locationKey;
    heading.scrollIntoView({ block: "start" });
    heading.setAttribute("tabindex", "-1");
    heading.focus({ preventScroll: true });
  }, [section, locationKey, summaryReady, tab]);

  if (lecture.isPending) return <LectureSkeleton />;
  if (lecture.isError) {
    return <LectureError error={lecture.error} onRetry={() => void lecture.refetch()} retrying={lecture.isFetching} />;
  }

  const data = lecture.data;
  const videoUrl = data.video_url ?? null;
  const audioUrl = videoUrl ? null : (data.audio_url ?? null);
  const embed = videoUrl || audioUrl ? null : resolveEmbed(data.embed_url);
  const hasPlayer = videoUrl !== null || audioUrl !== null || embed !== null;
  const summary = data.summary?.content_md.trim() ?? "";
  const showProcessing = isPending(data.status) || data.status === "failed";
  const progress = status.data ?? null;
  const failedSummarize = data.steps.find((step) => step.step === "summarize" && step.status === "failed");
  const regenerationError = data.status === "ready" && !errorDismissed ? (failedSummarize?.error ?? null) : null;
  const tabs = (
    <Tabs
      label="Материалы лекции"
      value={tab}
      onChange={(next) => setTab(next as PanelKind)}
      items={[
        {
          id: "summary",
          label: "Конспект",
          panel: summary ? (
            <div className="lecture__scroll summary" ref={summaryRef}>
              <Markdown source={summary} />
            </div>
          ) : (
            <PanelEmpty kind="summary" status={data.status} />
          ),
        },
        {
          id: "chapters",
          label: "Главы",
          panel:
            chapters.length > 0 ? (
              <div className="lecture__scroll">
                <Chapters
                  chapters={chapters}
                  currentTime={hasPlayer ? currentTime : null}
                  onSelect={hasPlayer ? playFrom : undefined}
                />
              </div>
            ) : (
              <PanelEmpty kind="chapters" status={data.status} />
            ),
        },
        {
          id: "transcript",
          label: "Расшифровка",
          panel:
            segments.length > 0 ? (
              <Transcript
                segments={segments}
                chapters={chapters}
                currentTime={hasPlayer ? currentTime : null}
                onSelect={hasPlayer ? playFrom : undefined}
              />
            ) : (
              <PanelEmpty kind="transcript" status={data.status} />
            ),
        },
      ]}
    />
  );
  const tabHasContent = {
    summary: summary !== "",
    chapters: chapters.length > 0,
    transcript: segments.length > 0,
  };

  return (
    <div className="lecture">
      <header className="lecture__header">
        <BackLink />
        <div className="lecture__title-row">
          <h1 className="lecture__title">{data.title}</h1>
          <div className="lecture__title-actions">
            <QuizButton lecture={data} />
            {data.status === "ready" && <ShareButton target={{ lectureId: data.id }} title={data.title} />}
            <LectureActions lecture={data} />
          </div>
        </div>
        <LectureMeta lecture={data} />
        <ExportActions
          lectureId={data.id}
          title={data.title}
          ready={data.status === "ready"}
          hasSegments={segments.length > 0}
        />
      </header>
      {regenerationError !== null && (
        <p className="processing__error" role="alert">
          Не удалось пересоздать главы и конспект, остались прежние. {regenerationError}{" "}
          <Button variant="ghost" size="sm" onClick={() => setErrorDismissed(true)}>
            Скрыть
          </Button>
        </p>
      )}
      {showProcessing && (
        <Processing
          status={progress?.status ?? data.status}
          queuePosition={progress?.queue_position ?? null}
          steps={progress?.steps ?? data.steps}
          onRetry={() => retry.mutate()}
          retrying={retry.isPending}
          retryError={retry.error}
          stalled={status.stalled}
        />
      )}
      <div className="lecture__body">
        <div className="lecture__media">
          {videoUrl ? (
            <VideoPlayer
              key={videoIdentity(videoUrl)}
              src={videoUrl}
              title={data.title}
              refreshSrc={async () => (await fetchLecture(id)).video_url ?? null}
              {...bind}
            />
          ) : audioUrl ? (
            <VideoPlayer
              key={videoIdentity(audioUrl)}
              src={audioUrl}
              title={data.title}
              refreshSrc={async () => (await fetchLecture(id)).audio_url ?? null}
              audio
              {...bind}
            />
          ) : embed ? (
            <EmbedPlayer
              key={data.embed_url}
              embed={embed}
              title={data.title}
              start={startAt ?? 0}
              currentTime={currentTime}
              sourceUrl={data.source_url}
              {...bind}
            />
          ) : (
            <NoVideo lecture={data} />
          )}
        </div>
        <section
          className={searching || tabHasContent[tab] ? "lecture__panel" : "lecture__panel lecture__panel--empty"}
          aria-label="Материалы лекции"
        >
          {data.status === "ready" ? (
            <SearchPanel scope={{ lectureId: data.id }} onActiveChange={setSearching}>
              {tabs}
            </SearchPanel>
          ) : (
            tabs
          )}
        </section>
      </div>
    </div>
  );
}
