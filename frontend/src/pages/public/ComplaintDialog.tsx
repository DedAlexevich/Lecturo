import { useId, useState, type FormEvent } from "react";
import { ApiError } from "../../app/queryClient";
import { Button } from "../../ui/Button";
import { Dialog } from "../../ui/Dialog";
import { useToast } from "../../ui/Toast";
import { useComplaint } from "./queries";
import "../../ui/Field.css";
import "../../ui/Input.css";

const reasonLimit = 5000;

function complaintError(error: Error) {
  if (error instanceof ApiError && error.status === 429) {
    return "Слишком много жалоб с этого адреса. Попробуйте позже.";
  }
  if (error instanceof ApiError && error.status === 404) {
    return "Ссылка больше не работает, жалобу отправить нельзя.";
  }
  return "Не получилось отправить жалобу. Попробуйте ещё раз.";
}

type ComplaintDialogProps = {
  token: string;
  title: string;
  onClose: () => void;
};

export function ComplaintDialog({ token, title, onClose }: ComplaintDialogProps) {
  const formId = useId();
  const fieldId = useId();
  const toast = useToast();
  const complaint = useComplaint(token);
  const [reason, setReason] = useState("");
  const [touched, setTouched] = useState(false);
  const empty = reason.trim() === "";
  const invalid = touched && empty;

  function close() {
    if (!complaint.isPending) onClose();
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    setTouched(true);
    if (empty || complaint.isPending) return;
    complaint.mutate(reason.trim(), {
      onSuccess: () => {
        toast.show("Жалоба отправлена. Мы проверим лекцию", "success");
        onClose();
      },
    });
  }

  return (
    <Dialog
      open
      dismissible={!complaint.isPending}
      title="Пожаловаться на лекцию"
      onClose={close}
      actions={
        <>
          <Button variant="secondary" disabled={complaint.isPending} onClick={close}>
            Отмена
          </Button>
          <Button type="submit" form={formId} loading={complaint.isPending}>
            Отправить
          </Button>
        </>
      }
    >
      <form id={formId} className="complaint" onSubmit={submit} noValidate>
        <p className="complaint__lead">
          Лекция «{title}». Опишите, что с ней не так: нарушены авторские права, оскорбления, личные данные или
          другое.
        </p>
        <div className="field">
          <label className="field__label" htmlFor={fieldId}>
            Причина
          </label>
          <textarea
            id={fieldId}
            className="input complaint__reason"
            value={reason}
            rows={5}
            maxLength={reasonLimit}
            autoFocus
            disabled={complaint.isPending}
            aria-invalid={invalid || undefined}
            aria-describedby={invalid ? `${fieldId}-error` : undefined}
            onChange={(event) => setReason(event.target.value)}
          />
          {invalid && (
            <p className="field__error" id={`${fieldId}-error`}>
              Напишите причину жалобы
            </p>
          )}
        </div>
        {complaint.isError && (
          <p className="complaint__error" role="alert">
            {complaintError(complaint.error)}
          </p>
        )}
      </form>
    </Dialog>
  );
}
