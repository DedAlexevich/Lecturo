import { Link, useParams } from "react-router";
import { ApiError } from "../../app/queryClient";
import { Button } from "../../ui/Button";
import { EmptyState } from "../../ui/EmptyState";
import { PublicCourse } from "./PublicCourse";
import { PublicLecture } from "./PublicLecture";
import { usePublicShare } from "./queries";
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

export function PublicSharePage() {
  const { token = "" } = useParams();
  const share = usePublicShare(token);

  if (share.isPending) return <PublicSkeleton />;

  if (share.isError) {
    if (share.error instanceof ApiError && (share.error.status === 404 || share.error.status === 422)) {
      return <Unavailable />;
    }
    return (
      <div className="public">
        <div className="lecture__error public__error" role="alert">
          <p>Не получилось открыть страницу. Проверьте соединение и попробуйте ещё раз.</p>
          <Button variant="secondary" size="sm" onClick={() => void share.refetch()} loading={share.isFetching}>
            Повторить
          </Button>
        </div>
      </div>
    );
  }

  const { lecture, course } = share.data;
  if (lecture) {
    return (
      <PublicLecture
        key={token}
        token={token}
        lecture={lecture}
        refreshVideo={async () => (await share.refetch()).data?.lecture?.video_url ?? null}
      />
    );
  }
  if (course) return <PublicCourse course={course} />;
  return <Unavailable />;
}
