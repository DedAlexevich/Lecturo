import { useCallback, useId, useState, type FormEvent } from "react";
import { signOut } from "../../app/session";
import { Button } from "../../ui/Button";
import { Dialog } from "../../ui/Dialog";
import { Field } from "../../ui/Field";
import { Input } from "../../ui/Input";
import { useToast } from "../../ui/Toast";
import { TelegramButton, telegramEnabled } from "../auth/TelegramButton";
import styles from "./SettingsSection.module.css";
import { getMiniAppInitData } from "./miniApp";
import { settingsError, useDeleteAccount, type TelegramUser } from "./settings";

export function DeleteAccount({ hasPassword }: { hasPassword: boolean }) {
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [missing, setMissing] = useState(false);
  const formId = useId();
  const remove = useDeleteAccount();
  const toast = useToast();
  const { mutate, reset } = remove;

  const finish = useCallback(() => {
    toast.show("Аккаунт удалён", "success");
    signOut();
  }, [toast]);

  const close = () => {
    setOpen(false);
    setPassword("");
    setMissing(false);
    reset();
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (password === "") {
      setMissing(true);
      return;
    }
    mutate({ password }, { onSuccess: finish });
  };

  const confirmTelegram = useCallback(
    (user: TelegramUser) => mutate({ telegram: user }, { onSuccess: finish }),
    [mutate, finish],
  );

  const confirmMiniApp = () => mutate({ telegram_init_data: getMiniAppInitData() }, { onSuccess: finish });

  const inMiniApp = Boolean(getMiniAppInitData());

  const failure = remove.isError ? settingsError(remove.error, "Подтверждение не прошло") : undefined;

  return (
    <>
      <div>
        <Button variant="danger" onClick={() => setOpen(true)}>
          Удалить аккаунт
        </Button>
      </div>
      <Dialog
        open={open}
        onClose={close}
        title="Удалить аккаунт?"
        actions={
          <>
            <Button variant="secondary" onClick={close}>
              Отмена
            </Button>
            {!hasPassword && inMiniApp && (
              <Button variant="danger" loading={remove.isPending} onClick={confirmMiniApp}>
                Удалить навсегда
              </Button>
            )}
            {hasPassword && (
              <Button type="submit" form={formId} variant="danger" loading={remove.isPending}>
                Удалить навсегда
              </Button>
            )}
          </>
        }
      >
        <div className={styles.dialogContent}>
          <p>Лекции, курсы, файлы и данные аккаунта будут удалены сразу. Вернуть их не получится.</p>
          {open && hasPassword && (
            <form id={formId} onSubmit={submit} noValidate>
              <Field label="Пароль для подтверждения" error={missing ? "Введите пароль" : undefined}>
                {(control) => (
                  <Input
                    {...control}
                    type="password"
                    autoComplete="current-password"
                    value={password}
                    onChange={(event) => {
                      setPassword(event.target.value);
                      setMissing(false);
                      reset();
                    }}
                  />
                )}
              </Field>
            </form>
          )}
          {open && !hasPassword && inMiniApp && (
            <p>Подтверждение придёт из Telegram автоматически: нажмите «Удалить навсегда».</p>
          )}
          {open && !hasPassword && !inMiniApp && (
            <div className={styles.confirmTelegram}>
              <p>Для подтверждения нажмите кнопку Telegram: аккаунт удалится сразу после входа.</p>
              {telegramEnabled ? (
                <TelegramButton
                  label="Подтвердить через Telegram"
                  fullWidth
                  loading={remove.isPending}
                  onAuth={confirmTelegram}
                  onError={(error) => toast.show(settingsError(error), "error")}
                />
              ) : (
                <p className={styles.alert}>Подтверждение через Telegram сейчас недоступно.</p>
              )}
            </div>
          )}
          {failure && (
            <p className={styles.alert} role="alert">
              {failure}
            </p>
          )}
        </div>
      </Dialog>
    </>
  );
}
