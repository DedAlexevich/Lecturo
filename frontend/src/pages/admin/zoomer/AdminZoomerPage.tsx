import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";
import { Button } from "../../../ui/Button";
import { Checkbox } from "../../../ui/Checkbox";
import { EmptyState } from "../../../ui/EmptyState";
import { Field } from "../../../ui/Field";
import { Input } from "../../../ui/Input";
import { Spinner } from "../../../ui/Spinner";
import { useToast } from "../../../ui/Toast";
import { errorMessage } from "../api";
import { formatSize } from "../backups/backupsApi";
import styles from "./Zoomer.module.css";
import {
  formatDuration,
  uploadZoomerVideo,
  useDeleteZoomerVideo,
  useReorderZoomerVideos,
  useUpdateZoomerVideo,
  useZoomerVideos,
  zoomerQueryKey,
  type ZoomerVideo,
} from "./zoomerApi";

const statusLabels: Record<ZoomerVideo["status"], string> = {
  processing: "Обрабатывается",
  ready: "Готов",
  failed: "Ошибка",
};

function UploadForm() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [source, setSource] = useState("");
  const [share, setShare] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!file) {
      setError("Выберите файл ролика");
      return;
    }
    setError(null);
    setShare(0);
    try {
      const video = await uploadZoomerVideo(file, { title: title.trim(), source: source.trim() }, setShare);
      toast.show(
        video.vertical === false
          ? "Ролик загружен и обрабатывается. Он не вертикальный 9:16, сбоку от лекции будет выглядеть хуже"
          : "Ролик загружен и обрабатывается",
        "success",
      );
      setFile(null);
      setTitle("");
      setSource("");
      void queryClient.invalidateQueries({ queryKey: zoomerQueryKey });
    } catch (failure) {
      setError(errorMessage(failure, "Не удалось загрузить ролик"));
    } finally {
      setShare(null);
    }
  };

  const busy = share !== null;

  return (
    <form className={styles.panel} onSubmit={(event) => void submit(event)} aria-labelledby="zoomer-upload-title">
      <h3 id="zoomer-upload-title">Загрузить ролик</h3>
      <p className={styles.rights}>
        Загружайте только свои ролики или ролики с открытой лицензией. Чужие записи игр, стримов и каналов не
        используйте, даже если они есть в открытом доступе.
      </p>
      <div className={styles.fileRow}>
        <Button variant="secondary" onClick={() => fileInput.current?.click()} disabled={busy}>
          {file ? "Выбрать другой файл" : "Выбрать файл"}
        </Button>
        <span className={file ? undefined : styles.muted} id="zoomer-file-hint">
          {file ? `${file.name}, ${formatSize(file.size)}` : "MP4 (H.264) или WebM, до 30 МБ и 3 минут, лучше вертикальный 9:16"}
        </span>
        <input
          ref={fileInput}
          type="file"
          accept="video/mp4,video/webm"
          className={styles.fileInput}
          tabIndex={-1}
          aria-label="Файл ролика"
          aria-describedby="zoomer-file-hint"
          onChange={(event) => {
            setFile(event.target.files?.[0] ?? null);
            event.target.value = "";
          }}
        />
      </div>
      <div className={styles.fields}>
        <Field label="Название">
          {(control) => (
            <Input {...control} value={title} maxLength={120} required onChange={(event) => setTitle(event.target.value)} />
          )}
        </Field>
        <Field label="Источник и лицензия" hint="Например: своя съёмка; или автор, ссылка и CC BY 4.0">
          {(control) => (
            <Input
              {...control}
              value={source}
              minLength={3}
              maxLength={500}
              required
              onChange={(event) => setSource(event.target.value)}
            />
          )}
        </Field>
      </div>
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      <div className={styles.actions}>
        <Button type="submit" loading={busy}>
          Загрузить
        </Button>
        {share !== null && <progress className={styles.progress} value={share} max={1} aria-label="Загрузка ролика" />}
        <span className={styles.muted}>Звук убираем, ролик пережимаем в 720p и делаем превью.</span>
      </div>
    </form>
  );
}

function StatusCell({ video }: { video: ZoomerVideo }) {
  return (
    <td>
      <span className={video.status === "failed" ? styles.failed : undefined}>{statusLabels[video.status]}</span>
      {video.status === "processing" && <Spinner size="sm" label="Обрабатывается" />}
      {video.error && <span className={styles.note}>{video.error}</span>}
      {video.vertical === false && <span className={styles.note}>Не 9:16</span>}
    </td>
  );
}

export function AdminZoomerPage() {
  const { data, isPending, isError, refetch } = useZoomerVideos();
  const update = useUpdateZoomerVideo();
  const reorder = useReorderZoomerVideos();
  const remove = useDeleteZoomerVideo();
  const toast = useToast();

  const notify = (fallback: string) => (failure: unknown) => toast.show(errorMessage(failure, fallback), "error");

  const move = (index: number, shift: number) => {
    if (!data) return;
    const ids = data.map((video) => video.id);
    const [moved] = ids.splice(index, 1);
    ids.splice(index + shift, 0, moved);
    reorder.mutate(ids, { onError: notify("Не удалось изменить порядок") });
  };

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h2>Ролики зумер-режима</h2>
        <p className={styles.muted}>
          Вертикальные ролики без звука, которые режим зумера показывает сбоку от лекции. Пользователям видны только
          готовые и включённые, по порядку из списка.
        </p>
      </header>

      <UploadForm />

      {isPending && <Spinner label="Загружаем список" />}
      {isError && (
        <div className={styles.state} role="alert">
          <p>Не удалось загрузить список роликов.</p>
          <Button variant="secondary" size="sm" onClick={() => void refetch()}>
            Повторить
          </Button>
        </div>
      )}
      {data && data.length === 0 && (
        <EmptyState title="Роликов пока нет" description="Загрузите первый, и он появится в режиме зумера после обработки." />
      )}
      {data && data.length > 0 && (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">
                  <span className={styles.srOnly}>Превью</span>
                </th>
                <th scope="col">Ролик</th>
                <th scope="col" className={styles.number}>
                  Длительность
                </th>
                <th scope="col" className={styles.number}>
                  Размер
                </th>
                <th scope="col">Статус</th>
                <th scope="col">Показ</th>
                <th scope="col">
                  <span className={styles.srOnly}>Действия</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {data.map((video, index) => (
                <tr key={video.id}>
                  <td>
                    {video.poster_url ? (
                      <img className={styles.poster} src={video.poster_url} alt="" loading="lazy" />
                    ) : (
                      <span className={styles.posterEmpty} aria-hidden="true" />
                    )}
                  </td>
                  <td className={styles.titleCell}>
                    <strong>{video.title}</strong>
                    <span className={styles.note}>{video.source}</span>
                  </td>
                  <td className={styles.number}>{formatDuration(video.duration_sec)}</td>
                  <td className={styles.number}>{video.size_bytes === null ? "—" : formatSize(video.size_bytes)}</td>
                  <StatusCell video={video} />
                  <td>
                    <Checkbox
                      label="Показывать"
                      checked={video.enabled}
                      disabled={update.isPending}
                      onChange={(event) =>
                        update.mutate(
                          { id: video.id, patch: { enabled: event.target.checked } },
                          { onError: notify("Не удалось сохранить") },
                        )
                      }
                    />
                  </td>
                  <td>
                    <div className={styles.rowActions}>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={index === 0 || reorder.isPending}
                        aria-label={`Поднять «${video.title}»`}
                        onClick={() => move(index, -1)}
                      >
                        Выше
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={index === data.length - 1 || reorder.isPending}
                        aria-label={`Опустить «${video.title}»`}
                        onClick={() => move(index, 1)}
                      >
                        Ниже
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={remove.isPending}
                        onClick={() => {
                          if (window.confirm(`Удалить ролик «${video.title}»? Файл удалится с сервера.`)) {
                            remove.mutate(video.id, { onError: notify("Не удалось удалить") });
                          }
                        }}
                      >
                        Удалить
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
