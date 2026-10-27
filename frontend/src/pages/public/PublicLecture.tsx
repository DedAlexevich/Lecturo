import { useMemo, useState } from "react";
import { Link } from "react-router";
import type { components } from "../../api/schema";
import { Button } from "../../ui/Button";
import { Tabs } from "../../ui/Tabs";
import { Chapters } from "../lecture/Chapters";
import { EmbedPlayer } from "../lecture/players/EmbedPlayer";
import { resolveEmbed } from "../lecture/players/embed";
import { VideoPlayer } from "../lecture/players/VideoPlayer";
import { usePlayer, videoIdentity } from "../lecture/players/player";
import { formatDuration } from "../lecture/time";
import { Transcript } from "../lecture/Transcript";
import { localNotes } from "../lecture/localNotes";
import { SummaryMarkdown } from "../lecture/SummaryMarkdown";
import { ComplaintDialog } from "./ComplaintDialog";
import { LocalBadge } from "./LocalBadge";
import "../lecture/lecture.css";

type Lecture = components["schemas"]["PublicLectureOut"];
type PanelKind = "summary" | "chapters" | "transcript";

const emptyNotes: Record<PanelKind, string> = {
  summary: "Для этой лекции конспекта нет.",
  chapters: "Лекция слишком короткая, чтобы делить её на главы.",
  transcript: "В записи не распознано ни одной фразы.",
};

type PublicLectureProps = {
  token: string;
  lecture: Lecture;
  courseLink?: string;
  refreshVideo: () => Promise<string | null>;
};

export function PublicLecture({ token, lecture, courseLink, refreshVideo }: PublicLectureProps) {
  const [tab, setTab] = useState<PanelKind>("summary");
  const [complaining, setComplaining] = useState(false);
  const { currentTime, playFrom, bind } = usePlayer();

  const segments = useMemo(() => [...lecture.segments].sort((a, b) => a.start - b.start), [lecture.segments]);
  const chapters = useMemo(() => [...lecture.chapters].sort((a, b) => a.start - b.start), [lecture.chapters]);
  const summary = lecture.summary?.content_md.trim() ?? "";
  const embed = lecture.video_url ? null : resolveEmbed(lecture.embed_url);
  const hasPlayer = lecture.video_url !== null || embed !== null;
  const tabHasContent = { summary: summary !== "", chapters: chapters.length > 0, transcript: segments.length > 0 };
  const note = (kind: PanelKind) => (
    <p className="lecture__panel-note">{lecture.processed_locally ? localNotes[kind] : emptyNotes[kind]}</p>
  );

  return (
    <article className="lecture">
      <header className="lecture__header">
        {courseLink && (
          <Link to={courseLink} className="lecture__back">
            Все лекции курса
          </Link>
        )}
        <div className="lecture__title-row">
          <h1 className="lecture__title">{lecture.title}</h1>
          <Button variant="ghost" size="sm" className="public__report" onClick={() => setComplaining(true)}>
            Пожаловаться
          </Button>
        </div>
        <div className="public__meta">
          {lecture.duration_sec !== null && <span>{formatDuration(lecture.duration_sec)}</span>}
          <span>Только чтение</span>
          {lecture.processed_locally && <LocalBadge />}
        </div>
      </header>
      <div className="lecture__body">
        <div className="lecture__media">
          {lecture.video_url ? (
            <VideoPlayer
              key={videoIdentity(lecture.video_url)}
              src={lecture.video_url}
              title={lecture.title}
              refreshSrc={refreshVideo}
              {...bind}
            />
          ) : embed ? (
            <EmbedPlayer
              key={lecture.embed_url}
              embed={embed}
              title={lecture.title}
              start={0}
              currentTime={currentTime}
              sourceUrl={null}
              {...bind}
            />
          ) : (
            <div className="lecture__no-video">
              <p className="lecture__no-video-title">
                {lecture.processed_locally ? "Видео осталось на устройстве автора" : "Видео недоступно"}
              </p>
              <p className="lecture__no-video-text">
                {lecture.processed_locally
                  ? "Лекцию обработали на устройстве, сюда попали только расшифровка и материалы."
                  : "Конспект, главы и расшифровка остаются на странице."}
              </p>
            </div>
          )}
        </div>
        <section
          className={tabHasContent[tab] ? "lecture__panel" : "lecture__panel lecture__panel--empty"}
          aria-label="Материалы лекции"
        >
          <Tabs
            label="Материалы лекции"
            value={tab}
            onChange={(next) => setTab(next as PanelKind)}
            items={[
              {
                id: "summary",
                label: "Конспект",
                panel: summary ? (
                  <div className="lecture__scroll summary">
                    <SummaryMarkdown source={summary} />
                  </div>
                ) : (
                  note("summary")
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
                    note("chapters")
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
                    note("transcript")
                  ),
              },
            ]}
          />
        </section>
      </div>
      {complaining && <ComplaintDialog token={token} lectureId={lecture.id} title={lecture.title} onClose={() => setComplaining(false)} />}
    </article>
  );
}
