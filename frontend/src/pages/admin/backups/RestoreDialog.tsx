import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { api } from "../../../api/client";
import { ApiError } from "../../../app/queryClient";
import { Button } from "../../../ui/Button";
import { Dialog } from "../../../ui/Dialog";
import { Field } from "../../../ui/Field";
import { Input } from "../../../ui/Input";
import { backupsQueryKey, errorDetail, type Backup } from "./backupsApi";
import styles from "./Backups.module.css";

type Props = { backup: Backup | null; onClose: () => void };

export function RestoreDialog({ backup, onClose }: Props) {
  const queryClient = useQueryClient();
  const [password, setPassword] = useState("");
  const [word, setWord] = useState("");

  useEffect(() => {
    if (backup === null) {
      setPassword("");
      setWord("");
    }
  }, [backup]);

  const restore = useMutation({
    mutationFn: async () => {
      const { error, response } = await api.POST("/api/v1/admin/backups/{name}/restore", {
        params: { path: { name: backup?.name ?? "" } },
        body: { password, confirmation: word },
      });
      if (!response.ok) throw new ApiError(response.status, error);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: backupsQueryKey });
      onClose();
    },
  });

  const ready = password.length > 0 && word === "RESTORE";

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (ready) restore.mutate();
  };

  return (
    <Dialog
      open={backup !== null}
      onClose={onClose}
      title="Восстановить базу из дампа"
      actions={
        <>
          <Button variant="secondary" onClick={onClose}>
            Отмена
          </Button>
          <Button type="submit" form="restore-form" variant="danger" disabled={!ready} loading={restore.isPending}>
            Восстановить
          </Button>
        </>
      }
    >
      <form id="restore-form" className={styles.dialogForm} onSubmit={submit}>
        <p>
          Текущая база будет заменена данными из <strong>{backup?.name}</strong>. Перед этим панель сохранит копию
          текущей базы, проверит дамп во временной базе и включит режим обслуживания: сайт будет недоступен, обработка
          лекций приостановится.
        </p>
        <Field label="Пароль администратора">
          {(control) => (
            <Input
              {...control}
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          )}
        </Field>
        <Field label="Введите слово RESTORE" error={restore.isError ? errorDetail(restore.error, "Не удалось запустить") : undefined}>
          {(control) => (
            <Input {...control} autoComplete="off" value={word} onChange={(event) => setWord(event.target.value)} />
          )}
        </Field>
      </form>
    </Dialog>
  );
}
