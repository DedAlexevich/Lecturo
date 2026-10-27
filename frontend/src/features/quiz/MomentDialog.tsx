import { useEffect } from "react";
import { Link } from "react-router";
import type { components } from "../../api/schema";
import { formatTimecode } from "../../lib/timecode";
import { EmbedPlayer } from "../../pages/lecture/players/EmbedPlayer";
import { resolveEmbed } from "../../pages/lecture/players/embed";
import { usePlayer, videoIdentity } from "../../pages/lecture/players/player";
import { VideoPlayer } from "../../pages/lecture/players/VideoPlayer";
import { fetchLecture } from "../../pages/lecture/useLecture";
import { Button } from "../../ui/Button";
import { Dialog } from "../../ui/Dialog";
import { fromQuizState, momentLink } from "./moment";

type Lecture = components["schemas"]["LectureDetail"];

export function hasMomentPlayer(lecture: Lecture) {
  return Boolean(lecture.video_url || lecture.audio_url || resolveEmbed(lecture.embed_url));
}

function MomentPlayer({ lecture, seconds }: { lecture: Lecture; seconds: number }) {
  const { currentTime, seek, bind } = usePlayer();
  const videoUrl = lecture.video_url ?? null;
  const audioUrl = videoUrl ? null : (lecture.audio_url ?? null);
  const embed = videoUrl || audioUrl ? null : resolveEmbed(lecture.embed_url);

  useEffect(() => {
    seek(seconds);
  }, [seconds, seek]);

  if (videoUrl || audioUrl) {
    const src = (videoUrl ?? audioUrl)!;
    return (
      <VideoPlayer
        key={videoIdentity(src)}
        src={src}
        title={lecture.title}
        refreshSrc={async () => {
          const fresh = await fetchLecture(lecture.id);
          return (videoUrl ? fresh.video_url : fresh.audio_url) ?? null;
        }}
        audio={!videoUrl}
        {...bind}
      />
    );
  }
  if (!embed) return null;
  return (
    <EmbedPlayer
      key={lecture.embed_url}
      embed={embed}
      title={lecture.title}
      start={seconds}
      currentTime={currentTime}
      sourceUrl={lecture.source_url}
      {...bind}
    />
  );
}

type MomentDialogProps = {
  lecture: Lecture;
  seconds: number | null;
  onClose: () => void;
};

export function MomentDialog({ lecture, seconds, onClose }: MomentDialogProps) {
  const open = seconds !== null;
  return (
    <Dialog
      open={open}
      onClose={onClose}
      className="moment-dialog"
      title={open ? `Момент лекции с ${formatTimecode(seconds)}` : "Момент лекции"}
      actions={
        open && (
          <>
            <Link to={momentLink(lecture.id, seconds)} state={fromQuizState} className="button button--secondary">
              Открыть страницу лекции
            </Link>
            <Button onClick={onClose}>Вернуться к квизу</Button>
          </>
        )
      }
    >
      {open && <MomentPlayer key={seconds} lecture={lecture} seconds={seconds} />}
    </Dialog>
  );
}
