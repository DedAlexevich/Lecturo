import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { api } from "../../../api/client";
import { ApiError } from "../../../app/queryClient";
import { Button } from "../../../ui/Button";
import { EmptyState } from "../../../ui/EmptyState";
import { Spinner } from "../../../ui/Spinner";
import { useToast } from "../../../ui/Toast";
import { formatDateTime } from "../../account/format";
import {
  backupsQueryKey,
  downloadBackup,
  errorDetail,
  formatSize,
  integrityLabels,
  jobStepLabels,
  sourceLabels,
  uploadBackup,
  useBackups,
  type Backup,
} from "./backupsApi";
import styles from "./Backups.module.css";
import { RestoreDialog } from "./RestoreDialog";

export function AdminBackupsPage() {
  const { data, isPending, isError, refetch } = useBackups();
  const queryClient = useQueryClient();
  const toast = useToast();
  const fileInput = useRef<HTMLInputElement>(null);
  const [restoring, setRestoring] = useState<Backup | null>(null);
  const [uploadShare, setUploadShare] = useState<number | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);

  const refresh = () => queryClient.invalidateQueries({ queryKey: backupsQueryKey });

  const create = useMutation({
    mutationFn: async () => {
      const { error, response } = await api.POST("/api/v1/admin/backups");
      if (!response.ok) throw new ApiError(response.status, error);
    },
    onSuccess: () => void refresh(),
    onError: (error) => toast.show(errorDetail(error, "Не удалось создать дамп"), "error"),
  });

  const remove = useMutation({
    mutationFn: async (name: string) => {
      const { error, response } = await api.DELETE("/api/v1/admin/backups/{name}", {
        params: { path: { name } },
      });
      if (!response.ok) throw new ApiError(response.status, error);
    },
    onSuccess: () => void refresh(),
    onError: (error) => toast.show(errorDetail(error, "Не удалось удалить"), "error"),
  });

  const upload = useMutation({
    mutationFn: (file: File) => uploadBackup(file, setUploadShare),
    onSuccess: (backup) => {
      toast.show(`Дамп загружен: ${backup.name}. Он ещё не применён`, "success");
      void refresh();
    },
    onError: (error) => toast.show(errorDetail(error, "Не удалось загрузить дамп"), "error"),
    onSettled: () => setUploadShare(null),
  });

  const download = async (name: string) => {
    setDownloading(name);
    try {
      await downloadBackup(name);
    } catch (error) {
      toast.show(errorDetail(error, "Не удалось скачать"), "error");
    } finally {
      setDownloading(null);
    }
  };

  const job = data?.job ?? null;
  const running = job?.state === "running";
  const busy = running || create.isPending || upload.isPending;

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h2>Бэкапы базы</h2>
        <p className={styles.muted}>Дампы из папки бэкапов: скачать, создать, загрузить и восстановить.</p>
      </header>

      {data?.maintenance && (
        <div className={styles.banner} role="status">
          <strong>Включён режим обслуживания</strong>
          <span>Сайт отвечает «идут работы», обработка лекций приостановлена.</span>
          {!running && (
            <div>
              <Button
                size="sm"
                variant="secondary"
                onClick={async () => {
                  await api.POST("/api/v1/admin/maintenance/disable");
                  void refresh();
                }}
              >
                Выключить режим обслуживания
              </Button>
            </div>
          )}
        </div>
      )}

      {job && (
        <div className={job.state === "failed" ? styles.bannerDanger : styles.banner} role={job.state === "failed" ? "alert" : "status"}>
          <strong>
            {job.kind === "restore" ? "Восстановление" : "Создание дампа"}
            {job.backup ? `: ${job.backup}` : ""}
          </strong>
          {job.state === "running" && <span>{jobStepLabels[job.step] ?? job.step}</span>}
          {job.state === "done" && <span>Готово, {formatDateTime(job.finished_at ?? job.started_at)}</span>}
          {job.state === "failed" && <span>{job.message}</span>}
        </div>
      )}

      <div className={styles.actions}>
        <Button onClick={() => create.mutate()} loading={create.isPending} disabled={busy}>
          Создать дамп сейчас
        </Button>
        <Button variant="secondary" onClick={() => fileInput.current?.click()} disabled={busy}>
          Загрузить дамп
        </Button>
        <input
          ref={fileInput}
          type="file"
          accept=".dump"
          className={styles.fileInput}
          tabIndex={-1}
          aria-label="Файл дампа"
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file) upload.mutate(file);
          }}
        />
        {uploadShare !== null && (
          <progress className={styles.progress} value={uploadShare} max={1} aria-label="Загрузка дампа" />
        )}
        <Button variant="ghost" onClick={() => void refetch()}>
          Обновить список
        </Button>
      </div>

      {isPending && (
        <div className={styles.state}>
          <Spinner label="Загружаем список" />
        </div>
      )}
      {isError && (
        <div className={styles.state} role="alert">
          <p>Не удалось загрузить список. Если идёт восстановление, подождите.</p>
          <Button variant="secondary" size="sm" onClick={() => void refetch()}>
            Повторить
          </Button>
        </div>
      )}
      {data && data.items.length === 0 && (
        <EmptyState title="Дампов нет" description="Создайте дамп кнопкой выше или загрузите файл." />
      )}
      {data && data.items.length > 0 && (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Файл</th>
                <th scope="col">Тип</th>
                <th scope="col">Дата</th>
                <th scope="col">Размер</th>
                <th scope="col">Целостность</th>
                <th scope="col">
                  <span className={styles.srOnly}>Действия</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((item) => (
                <tr key={item.name}>
                  <td className={styles.name}>{item.name}</td>
                  <td>{sourceLabels[item.source] ?? item.source}</td>
                  <td className={styles.nowrap}>{formatDateTime(item.modified_at)}</td>
                  <td className={styles.nowrap}>{formatSize(item.size)}</td>
                  <td className={item.integrity === "broken" ? styles.broken : undefined}>
                    {integrityLabels[item.integrity]}
                    {item.dump_major !== null && <span className={styles.muted}> · PostgreSQL {item.dump_major}</span>}
                  </td>
                  <td>
                    <div className={styles.rowActions}>
                      <Button
                        size="sm"
                        variant="secondary"
                        loading={downloading === item.name}
                        onClick={() => void download(item.name)}
                      >
                        Скачать
                      </Button>
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={!item.restorable || busy}
                        onClick={() => setRestoring(item)}
                      >
                        Восстановить
                      </Button>
                      {item.source !== "lecturo" && (
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={busy}
                          onClick={() => {
                            if (window.confirm(`Удалить ${item.name}?`)) remove.mutate(item.name);
                          }}
                        >
                          Удалить
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <RestoreDialog backup={restoring} onClose={() => setRestoring(null)} />
    </div>
  );
}
