import { Link, useParams } from "react-router";
import { ApiError } from "../../app/queryClient";
import { Button } from "../../ui/Button";
import { EmptyState } from "../../ui/EmptyState";
import { Spinner } from "../../ui/Spinner";
import { formatDate } from "./formatDate";
import { Markdown } from "./markdown";
import { useLegalDocument } from "./useLegalDocument";
import "./legal.css";

const metaLines = [/^#\s+.*$/m, /^Редакция от .*$/m, /^Вступает в силу с .*$/m, /^Изменения: .*$/m];

function bodyOf(content: string) {
  return metaLines.reduce((body, line) => body.replace(line, ""), content);
}

export function LegalPage() {
  const { slug = "" } = useParams();
  const { data, error, isPending, refetch } = useLegalDocument(slug);

  if (isPending) {
    return (
      <div className="legal legal--loading">
        <Spinner size="lg" />
      </div>
    );
  }

  if (!data) {
    const notFound = error instanceof ApiError && error.status === 404;
    return (
      <EmptyState
        title={notFound ? "Такого документа нет" : "Не удалось загрузить документ"}
        description={notFound ? "Возможно, ссылка устарела." : "Проверьте соединение и попробуйте ещё раз."}
        action={
          notFound ? (
            <Link to="/">На главную</Link>
          ) : (
            <Button variant="secondary" onClick={() => refetch()}>
              Повторить
            </Button>
          )
        }
      />
    );
  }

  return (
    <article className="legal">
      <header className="legal__header">
        <h1 className="legal__title">{data.title}</h1>
        <p className="legal__revision">
          Редакция от {formatDate(data.revision_date)}
          {data.effective_date !== data.revision_date && `, вступает в силу с ${formatDate(data.effective_date)}`}
        </p>
        {data.changes && <p className="legal__changes">Что изменилось: {data.changes}</p>}
      </header>
      <div className="legal__body">
        <Markdown source={bodyOf(data.content_md)} />
      </div>
    </article>
  );
}
