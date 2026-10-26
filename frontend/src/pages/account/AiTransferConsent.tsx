import { useCallback, useState } from "react";
import { Link } from "react-router";
import { Button } from "../../ui/Button";
import { Dialog } from "../../ui/Dialog";
import { useToast } from "../../ui/Toast";
import { formatDate } from "./format";
import styles from "./SettingsSection.module.css";
import { settingsError, useRevokeAiTransfer, type Me } from "./settings";

export function AiTransferConsent({ me }: { me: Me }) {
  const [open, setOpen] = useState(false);
  const revoke = useRevokeAiTransfer();
  const toast = useToast();
  const { reset } = revoke;
  const acceptedAt = me.ai_transfer_accepted_at;

  const close = useCallback(() => {
    setOpen(false);
    reset();
  }, [reset]);

  const confirm = () =>
    revoke.mutate(undefined, {
      onSuccess: () => {
        toast.show("Согласие отозвано", "success");
        close();
      },
    });

  if (!acceptedAt) {
    return (
      <p className={styles.muted}>
        Согласия нет, серверная обработка лекций недоступна. Окно с согласием появится при добавлении следующей лекции.
      </p>
    );
  }

  return (
    <>
      <p className={styles.muted}>
        Дано {formatDate(acceptedAt)}. <Link to="/legal/ai-transfer">Текст согласия</Link>
      </p>
      <div>
        <Button variant="secondary" onClick={() => setOpen(true)}>
          Отозвать согласие
        </Button>
      </div>
      <Dialog
        open={open}
        onClose={close}
        title="Отозвать согласие?"
        actions={
          <>
            <Button variant="secondary" onClick={close}>
              Отмена
            </Button>
            <Button variant="danger" loading={revoke.isPending} onClick={confirm}>
              Отозвать
            </Button>
          </>
        }
      >
        <div className={styles.dialogContent}>
          <p>
            После отзыва мы не сможем расшифровывать и разбирать лекции на сервере: обработка остановится, пока вы не дадите согласие снова.
          </p>
          {revoke.isError && (
            <p className={styles.alert} role="alert">
              {settingsError(revoke.error)}
            </p>
          )}
        </div>
      </Dialog>
    </>
  );
}
