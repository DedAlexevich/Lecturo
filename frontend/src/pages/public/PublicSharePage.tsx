import { Link, useParams } from "react-router";
import { ApiError } from "../../app/queryClient";
import { Button } from "../../ui/Button";
import { EmptyState } from "../../ui/EmptyState";
import { PublicCourse } from "./PublicCourse";
import { PublicLecture } from "./PublicLecture";
import { fetchPublicCourseLecture, fetchPublicShare, usePublicCourseLecture, usePublicShare } from "./queries";
import "../lecture/lecture.css";
import "./public.css";

function PublicSkeleton() {
  return (
    <div className="public" aria-busy="true" aria-label="Загружаем страницу">
      <span className="public__bar public__bar--title" />
      <span className="public__bar public__bar--meta" />
      <span className="public__bar public__bar--body" />
    </div>
  );
}

function Unavailable() {
  return (
    <div className="public">
      <EmptyState
        title="Ссылка больше не работает"
        description="Владелец отозвал её или удалил материал. Попросите у него новую ссылку."
        action={<Link to="/">Перейти в Lecturo</Link>}
      />
    </div>
  );
}

function ShareFailure({ error, retrying, onRetry }: { error: Error; retrying: boolean; onRetry: () => void }) {
  if (error instanceof ApiError && (error.status === 404 || error.status === 422)) {
    return <Unavailable />;
  }
  return (
    <div className="public">
      <div className="lecture__error public__error" role="alert">
        <p>Не получилось открыть страницу. Проверьте соединение и попробуйте ещё раз.</p>
        <Button variant="secondary" size="sm" onClick={onRetry} loading={retrying}>
          Повторить
        </Button>
      </div>
    </div>
  );
}

function SharedMaterial({ token }: { token: string }) {
  const share = usePublicShare(token);

  if (share.isPending) return <PublicSkeleton />;
  if (share.isError) {
    return <ShareFailure error={share.error} retrying={share.isFetching} onRetry={() => void share.refetch()} />;
  }

  const { lecture, course } = share.data;
  if (lecture) {
    return (
      <PublicLecture
        key={token}
        token={token}
        lecture={lecture}
        refreshVideo={async () => (await fetchPublicShare(token)).lecture?.video_url ?? null}
      />
    );
  }
  if (course) return <PublicCourse token={token} course={course} />;
  return <Unavailable />;
}

function CourseLecture({ token, lectureId }: { token: string; lectureId: string }) {
  const lecture = usePublicCourseLecture(token, lectureId);

  if (lecture.isPending) return <PublicSkeleton />;
  if (lecture.isError) {
    return <ShareFailure error={lecture.error} retrying={lecture.isFetching} onRetry={() => void lecture.refetch()} />;
  }

  return (
    <PublicLecture
      key={`${token}/${lectureId}`}
      token={token}
      lecture={lecture.data}
      courseLink={`/s/${token}`}
      refreshVideo={async () => (await fetchPublicCourseLecture(token, lectureId)).video_url}
    />
  );
}

export function PublicSharePage() {
  const { token = "", lectureId } = useParams();
  return lectureId ? <CourseLecture token={token} lectureId={lectureId} /> : <SharedMaterial token={token} />;
}
