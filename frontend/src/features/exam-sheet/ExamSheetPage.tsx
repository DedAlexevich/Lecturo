import { useState } from "react";
import { Link, useParams } from "react-router";
import { ApiError } from "../../app/queryClient";
import { useCourse } from "../../pages/course/queries";
import { Button } from "../../ui/Button";
import { EmptyState } from "../../ui/EmptyState";
import { Spinner } from "../../ui/Spinner";
import { Tabs } from "../../ui/Tabs";
import { useAiTransferConsent } from "../consent/useAiTransferConsent";
import { Cheatsheet, DefinitionList, TicketList } from "./ExamSheetContent";
import { ExamSheetPrint } from "./ExamSheetPrint";
import { definitionsCount, ticketsCount } from "./format";
import { PrintButton } from "./PrintButton";
import { createErrorText, definitionsOf, errorCode, useCreateExamSheet, useExamSheet, type Definition, type ExamSheet } from "./queries";
import "./exam-sheet.css";

const sheetStates = ["subscription_required", "exam_sheet_processing", "exam_sheet_not_found", "exam_sheet_failed"];

function SheetSkeleton() {
  return (
    <div className="exam-sheet__skeleton" aria-busy="true" aria-label="Загружаем памятку">
      <span className="exam-skeleton exam-skeleton--tabs" />
      <span className="exam-skeleton exam-skeleton--row" />
      <span className="exam-skeleton exam-skeleton--row" />
      <span className="exam-skeleton exam-skeleton--row exam-skeleton--short" />
    </div>
  );
}

function Processing() {
  return (
    <div className="exam-sheet__processing">
      <Spinner size="md" label="Собираем памятку" />
      <div>
        <h2 className="exam-sheet__state-title">Собираем памятку</h2>
        <p className="exam-sheet__state-text">
          Обычно это занимает несколько минут. Можно уйти со страницы: памятка сохранится в курсе.
        </p>
      </div>
    </div>
  );
}

function Refreshing() {
  return (
    <div className="exam-sheet__notice" role="status">
      <Spinner size="sm" label="Обновляем памятку" />
      <p className="exam-sheet__notice-text">Обновляем памятку. Пока показана прежняя версия.</p>
    </div>
  );
}

function SheetTabs({ sheet, definitions }: { sheet: ExamSheet; definitions: Definition[] }) {
  return (
    <Tabs
      label="Разделы памятки"
      items={[
        { id: "tickets", label: "Билеты", panel: <TicketList tickets={sheet.tickets} /> },
        { id: "definitions", label: "Определения", panel: <DefinitionList definitions={definitions} /> },
        { id: "cheatsheet", label: "Шпаргалка", panel: <Cheatsheet source={sheet.cheatsheet_md} /> },
      ]}
    />
  );
}

export function ExamSheetPage() {
  const { id = "" } = useParams();
  const course = useCourse(id);
  const sheet = useExamSheet(id);
  const create = useCreateExamSheet(id);
  const { requireConsent, dialog: consentDialog } = useAiTransferConsent();

  const code = errorCode(sheet.error);
  const knownState = code !== null && sheetStates.includes(code);
  const courseMissing = sheet.error instanceof ApiError && sheet.error.status === 404 && !knownState;
  const data = sheet.data;
  const definitions = data ? definitionsOf(data) : [];
  const courseTitle = course.data?.title ?? "";
  const [sawProcessing, setSawProcessing] = useState(false);

  if (code === "exam_sheet_processing" && !sawProcessing) setSawProcessing(true);
  const buildFailed =
    (code === "exam_sheet_failed" || (sawProcessing && code === "exam_sheet_not_found")) && !create.isPending;

  const startCreate = () =>
    requireConsent(() => {
      setSawProcessing(false);
      create.mutate();
    });

  return (
    <div className="exam-sheet">
      <header className="exam-sheet__head">
        <div className="exam-sheet__heading">
          <Link to={`/courses/${id}`} className="exam-sheet__back">
            {courseTitle ? `Курс «${courseTitle}»` : "К курсу"}
          </Link>
          <h1 className="exam-sheet__title">Памятка к экзамену</h1>
          {data && (
            <p className="exam-sheet__summary">
              {ticketsCount(data.tickets.length)} · {definitionsCount(definitions.length)}
            </p>
          )}
        </div>
        {data && <PrintButton key={id} courseId={id} />}
      </header>

      {sheet.isPending && <SheetSkeleton />}

      {code === "subscription_required" && (
        <EmptyState
          title="Памятка доступна с подпиской"
          description="В подписке больше часов распознавания в неделю, квиз, памятка к экзамену, чат по лекции и долгое хранение видео."
          action={
            <Link to="/account#purchase" className="button button--primary button--md exam-sheet__plans">
              Посмотреть тарифы
            </Link>
          }
        />
      )}

      {code === "exam_sheet_processing" && <Processing />}

      {(code === "exam_sheet_not_found" || code === "exam_sheet_failed") && (
        <EmptyState
          title="Памятки пока нет"
          description="Соберём билеты, определения и шпаргалку из конспектов всех лекций курса. Потом её можно распечатать."
          action={
            <div className="exam-sheet__create">
              <Button onClick={startCreate} loading={create.isPending}>
                Собрать памятку
              </Button>
              {create.isError && (
                <p className="exam-sheet__alert" role="alert">
                  {createErrorText(create.error)}
                </p>
              )}
              {buildFailed && !create.isError && (
                <p className="exam-sheet__alert" role="alert">
                  Не получилось собрать памятку. Попробуйте ещё раз.
                </p>
              )}
            </div>
          }
        />
      )}

      {courseMissing && (
        <EmptyState
          title="Курс не найден"
          description="Возможно, его удалили или ссылка неполная."
          action={<Link to="/">Все лекции</Link>}
        />
      )}

      {sheet.isError && !data && !knownState && !courseMissing && (
        <div className="exam-sheet__error" role="alert">
          <p>Не получилось загрузить памятку.</p>
          <button type="button" className="exam-sheet__retry" onClick={() => sheet.refetch()}>
            Повторить
          </button>
        </div>
      )}

      {data?.processing && <Refreshing />}

      {data && data.outdated && !data.processing && (
        <div className="exam-sheet__notice">
          <div className="exam-sheet__notice-body">
            <p className="exam-sheet__notice-text">
              Состав курса изменился после сборки памятки. Соберите её заново, чтобы в ней были все лекции курса.
            </p>
            {create.isError && (
              <p className="exam-sheet__alert" role="alert">
                {createErrorText(create.error)}
              </p>
            )}
          </div>
          <Button variant="secondary" size="sm" onClick={startCreate} loading={create.isPending}>
            Обновить памятку
          </Button>
        </div>
      )}

      {data && <SheetTabs sheet={data} definitions={definitions} />}
      {data && <ExamSheetPrint courseTitle={courseTitle} sheet={data} definitions={definitions} />}
      {consentDialog}
    </div>
  );
}
