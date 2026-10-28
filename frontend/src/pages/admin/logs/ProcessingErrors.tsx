import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { api } from "../../../api/client";
import { ApiError } from "../../../app/queryClient";
import { Button } from "../../../ui/Button";
import { EmptyState } from "../../../ui/EmptyState";
import { Spinner } from "../../../ui/Spinner";
import { useToast } from "../../../ui/Toast";
import { formatDateTime } from "../../account/format";
import styles from "./Logs.module.css";
import { pageSize, stepLabels, useProcessingErrors } from "./logsApi";

function retryMessage(error: unknown) {
  if (error instanceof ApiError) {
    const detail = (error.body as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === "string") return detail;
  }
  return "Не удалось перезапустить обработку";
}

export function ProcessingErrors() {
  const [onlyFailed, setOnlyFailed] = useState(true);
  const [offset, setOffset] = useState(0);
  const { data, isPending, isError, refetch } = useProcessingErrors(onlyFailed, offset);
  const queryClient = useQueryClient();
  const toast = useToast();

  const retry = useMutation({
    mutationFn: async (lectureId: string) => {
      const { error, response } = await api.POST("/api/v1/admin/processing-errors/{lecture_id}/retry", {
        params: { path: { lecture_id: lectureId } },
      });
      if (!response.ok) throw new ApiError(response.status, error);
    },
    onSuccess: () => {
      toast.show("Обработка поставлена в очередь", "success");
      void queryClient.invalidateQueries({ queryKey: ["admin", "processing-errors"] });
    },
    onError: (error) => toast.show(retryMessage(error), "error"),
  });

  return (
    <div className={styles.page}>
      <div className={styles.controls}>
        <label className={styles.check}>
          <input
            type="checkbox"
            checked={onlyFailed}
            onChange={(event) => {
              setOnlyFailed(event.target.checked);
              setOffset(0);
            }}
          />
          Только лекции в статусе «упала»
        </label>
        <Button variant="secondary" onClick={() => void refetch()}>
          Обновить
        </Button>
      </div>

      {isPending && (
        <div className={styles.state}>
          <Spinner label="Загружаем ошибки" />
        </div>
      )}
      {isError && (
        <div className={styles.state} role="alert">
          <p>Не удалось загрузить ошибки.</p>
          <Button variant="secondary" size="sm" onClick={() => void refetch()}>
            Повторить
          </Button>
        </div>
      )}
      {data && data.items.length === 0 && (
        <EmptyState title="Упавших шагов нет" description="Здесь появятся шаги обработки, которые закончились ошибкой." />
      )}
      {data && data.items.length > 0 && (
        <>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col">Когда</th>
                  <th scope="col">Лекция</th>
                  <th scope="col">Шаг</th>
                  <th scope="col">Причина</th>
                  <th scope="col">Пользователь</th>
                  <th scope="col">
                    <span className={styles.srOnly}>Действия</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={`${item.lecture_id}-${item.step}`}>
                    <td className={styles.nowrap}>{formatDateTime(item.failed_at)}</td>
                    <td>
                      <Link to={`/lectures/${item.lecture_id}`}>{item.lecture_title || "Без названия"}</Link>
                    </td>
                    <td>
                      {stepLabels[item.step]}
                      <div className={styles.muted}>попыток: {item.attempts}</div>
                    </td>
                    <td className={styles.errorText}>{item.error || "Причина не записана"}</td>
                    <td>{item.user_label || "Аккаунт удалён"}</td>
                    <td>
                      {item.can_retry && (
                        <Button
                          size="sm"
                          variant="secondary"
                          loading={retry.isPending && retry.variables === item.lecture_id}
                          onClick={() => retry.mutate(item.lecture_id)}
                        >
                          Перезапустить
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className={styles.pager}>
            <Button variant="secondary" size="sm" disabled={offset === 0} onClick={() => setOffset(offset - pageSize)}>
              Назад
            </Button>
            <span className={styles.muted}>
              {offset + 1}–{offset + data.items.length} из {data.total}
            </span>
            <Button
              variant="secondary"
              size="sm"
              disabled={offset + pageSize >= data.total}
              onClick={() => setOffset(offset + pageSize)}
            >
              Дальше
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
