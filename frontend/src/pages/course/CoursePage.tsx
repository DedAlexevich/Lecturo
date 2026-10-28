import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ApiError } from "../../app/queryClient";
import { useAiTransferConsent } from "../../features/consent/useAiTransferConsent";
import { createErrorText, useCreateExamSheet, useExamSheet } from "../../features/exam-sheet/queries";
import { SearchPanel } from "../../features/search/SearchPanel";
import { Button } from "../../ui/Button";
import { Dialog } from "../../ui/Dialog";
import { EmptyState } from "../../ui/EmptyState";
import { useToast } from "../../ui/Toast";
import { ShareButton } from "../../features/share/ShareButton";
import { lecturesCount } from "../home/format";
import { useLectures } from "../home/queries";
import { AddLecturesDialog } from "./AddLecturesDialog";
import { CourseFormDialog } from "./CourseFormDialog";
import { CourseLectureList, CourseLectureListSkeleton } from "./CourseLectureList";
import { useAddLectures, useCourse, useDeleteCourse, useRemoveLecture, useUpdateCourse } from "./queries";
import "./course.css";

type OpenDialog = "add" | "rename" | "delete" | null;

function isMissing(error: Error | null) {
  return error instanceof ApiError && (error.status === 404 || error.status === 422);
}

function BackLink() {
  return (
    <Link to="/" className="course__back">
      Все лекции
    </Link>
  );
}

function CourseHeaderSkeleton() {
  return (
    <header className="course__head" aria-busy="true" aria-label="Загружаем курс">
      <div className="course__heading">
        <BackLink />
        <span className="course-skeleton course-skeleton--title" />
        <span className="course-skeleton course-skeleton--meta" />
      </div>
    </header>
  );
}

export function CoursePage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const course = useCourse(id);
  const lectures = useLectures(id);
  const examSheet = useExamSheet(id);
  const rebuildSheet = useCreateExamSheet(id);
  const { requireConsent, waiting: consentWaiting, dialog: consentDialog } = useAiTransferConsent();
  const rename = useUpdateCourse(id);
  const remove = useDeleteCourse(id);
  const addLectures = useAddLectures(id);
  const removeLecture = useRemoveLecture(id);
  const [dialog, setDialog] = useState<OpenDialog>(null);

  function closeDialog() {
    setDialog(null);
    rename.reset();
    remove.reset();
    addLectures.reset();
  }

  if (isMissing(course.error)) {
    return (
      <div className="course">
        <BackLink />
        <EmptyState
          level={1}
          title="Курс не найден"
          description="Возможно, его удалили или ссылка неполная."
          action={<Link to="/">Все лекции</Link>}
        />
      </div>
    );
  }

  if (course.isError) {
    return (
      <div className="course">
        <BackLink />
        <div className="course__error" role="alert">
          <p>Не получилось загрузить курс.</p>
          <button type="button" className="course__text-action" onClick={() => course.refetch()}>
            Повторить
          </button>
        </div>
      </div>
    );
  }

  const data = course.data;
  const items = lectures.data;
  const isEmpty = items?.length === 0;
  const openAdd = () => setDialog("add");

  return (
    <div className="course">
      {data ? (
        <header className="course__head">
          <div className="course__heading">
            <BackLink />
            <h1 className="course__title">{data.title}</h1>
            {data.description && <p className="course__description">{data.description}</p>}
            <p className="course__summary">{lecturesCount(items?.length ?? data.lecture_count)}</p>
            {examSheet.data?.processing ? (
              <p className="course__note course__note--quiet" role="status">
                Обновляем памятку к экзамену.{" "}
                <Link to={`/courses/${data.id}/exam-sheet`}>Открыть памятку</Link>
              </p>
            ) : (
              examSheet.data?.outdated && (
                <p className="course__note">
                  Состав курса изменился, памятка к экзамену собрана по прежнему списку лекций.{" "}
                  <button
                    type="button"
                    className="course__note-action"
                    disabled={rebuildSheet.isPending || consentWaiting}
                    onClick={() =>
                      requireConsent(() =>
                        rebuildSheet.mutate(undefined, {
                          onError: (error) => toast.show(createErrorText(error), "error"),
                        }),
                      )
                    }
                  >
                    {rebuildSheet.isPending || consentWaiting ? "Запускаем" : "Обновить памятку"}
                  </button>
                </p>
              )
            )}
          </div>
          <div className="course__actions">
            {items && items.length > 0 && (
              <Link to={`/courses/${data.id}/exam-sheet`} className="course__text-action">
                Памятка к экзамену
              </Link>
            )}
            <ShareButton target={{ courseId: data.id }} title={data.title} />
            <button type="button" className="course__text-action" onClick={() => setDialog("rename")}>
              Переименовать
            </button>
            <button
              type="button"
              className="course__text-action course__text-action--quiet"
              onClick={() => setDialog("delete")}
            >
              Удалить курс
            </button>
            {!isEmpty && <Button onClick={openAdd}>Добавить лекции</Button>}
          </div>
        </header>
      ) : (
        <CourseHeaderSkeleton />
      )}

      {items && items.length > 0 && <SearchPanel scope={{ courseId: id }} />}
      <section className="course__lectures" aria-label="Лекции курса">
        {lectures.isPending && <CourseLectureListSkeleton />}
        {lectures.isError && !items && !isMissing(lectures.error) && (
          <div className="course__error" role="alert">
            <p>Не получилось загрузить лекции курса.</p>
            <button type="button" className="course__text-action" onClick={() => lectures.refetch()}>
              Повторить
            </button>
          </div>
        )}
        {isEmpty && (
          <EmptyState
            title="В курсе пока нет лекций"
            description="Соберите сюда записи одного предмета. Одна лекция может быть сразу в нескольких курсах."
            action={
              <Button onClick={openAdd} disabled={!data}>
                Добавить лекции
              </Button>
            }
          />
        )}
        {items && items.length > 0 && (
          <CourseLectureList
            lectures={items}
            removingId={removeLecture.isPending ? removeLecture.variables : undefined}
            onRemove={(lecture) =>
              removeLecture.mutate(lecture.id, {
                onSuccess: () => toast.show(`«${lecture.title}» убрана из курса`, "success"),
                onError: () => toast.show("Не получилось убрать лекцию из курса", "error"),
              })
            }
          />
        )}
      </section>

      {data && dialog === "rename" && (
        <CourseFormDialog
          title="Переименовать курс"
          submitLabel="Сохранить"
          initial={{ title: data.title, description: data.description }}
          pending={rename.isPending}
          failed={rename.isError}
          onClose={closeDialog}
          onSubmit={(fields) => rename.mutate(fields, { onSuccess: closeDialog })}
        />
      )}

      {data && dialog === "add" && (
        <AddLecturesDialog
          courseTitle={data.title}
          inCourse={items ?? []}
          pending={addLectures.isPending}
          failed={addLectures.isError}
          onClose={closeDialog}
          onSubmit={(lectureIds) =>
            addLectures.mutate(lectureIds, {
              onSuccess: () => {
                closeDialog();
                toast.show(`В курс добавлено: ${lecturesCount(lectureIds.length)}`, "success");
              },
            })
          }
        />
      )}

      {data && dialog === "delete" && (
        <Dialog
          open
          onClose={closeDialog}
          title="Удалить курс?"
          actions={
            <>
              <Button variant="secondary" onClick={closeDialog}>
                Отмена
              </Button>
              <Button
                variant="danger"
                loading={remove.isPending}
                onClick={() =>
                  remove.mutate(undefined, {
                    onSuccess: () => {
                      toast.show(`Курс «${data.title}» удалён`);
                      navigate("/", { replace: true });
                    },
                  })
                }
              >
                Удалить
              </Button>
            </>
          }
        >
          <p>
            Курс «{data.title}» исчезнет из списка. Сами лекции останутся в разделе «Все лекции» и в других курсах.
          </p>
          {remove.isError && (
            <p className="course-form__error" role="alert">
              Не получилось удалить курс. Попробуйте ещё раз.
            </p>
          )}
        </Dialog>
      )}
      {consentDialog}
    </div>
  );
}
