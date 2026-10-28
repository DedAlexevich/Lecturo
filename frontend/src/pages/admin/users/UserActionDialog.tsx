import { useState, type FormEvent } from "react";
import { Button } from "../../../ui/Button";
import { Dialog } from "../../../ui/Dialog";
import { Field } from "../../../ui/Field";
import { Input } from "../../../ui/Input";
import { useToast } from "../../../ui/Toast";
import { formatDays } from "../../account/format";
import shared from "../AdminPage.module.css";
import { errorMessage } from "../api";
import { useUserAction, type UserAction } from "./api";
import styles from "./Users.module.css";

export type ActionKind = UserAction["kind"];

const titles: Record<ActionKind, string> = {
  admin: "Назначить админом",
  hours: "Начислить часы",
  subscription: "Продлить подписку",
  block: "Заблокировать аккаунт",
  unblock: "Разблокировать аккаунт",
};

const amountLimits = {
  hours: { label: "Сколько часов", min: 1, max: 1000, initial: "5" },
  subscription: { label: "На сколько дней", min: 1, max: 366, initial: "30" },
};

function describe(kind: ActionKind, amount: number) {
  if (kind === "admin") return "Права администратора выданы";
  if (kind === "hours") return `Начислено ${amount} ч`;
  if (kind === "subscription") return `Подписка продлена на ${formatDays(amount)}`;
  if (kind === "block") return "Аккаунт заблокирован";
  return "Аккаунт разблокирован";
}

type DialogProps = {
  userId: string;
  userName: string;
  kind: ActionKind | null;
  onClose: () => void;
};

function ActionForm({ userId, userName, kind, onClose }: DialogProps & { kind: ActionKind }) {
  const limits = kind === "hours" || kind === "subscription" ? amountLimits[kind] : null;
  const [amount, setAmount] = useState(limits?.initial ?? "");
  const [reason, setReason] = useState("");
  const action = useUserAction(userId);
  const toast = useToast();
  const value = Number(amount);
  const amountValid = !limits || (Number.isInteger(value) && value >= limits.min && value <= limits.max);
  const needsReason = kind !== "admin";
  const reasonValid = !needsReason || reason.trim().length >= 3;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!amountValid || !reasonValid) return;
    const text = reason.trim();
    const payload: UserAction =
      kind === "admin"
        ? { kind }
        : kind === "hours"
          ? { kind, hours: value, reason: text }
          : kind === "subscription"
            ? { kind, days: value, reason: text }
            : { kind, reason: text };
    action.mutate(payload, {
      onSuccess: () => {
        toast.show(describe(kind, value), "success");
        onClose();
      },
    });
  };

  return (
    <form className={styles.actionForm} onSubmit={submit}>
      {kind === "block" && (
        <p>
          {userName} сразу выйдет на всех устройствах и не сможет войти, пока аккаунт не разблокируют. Лекции и
          платежи останутся.
        </p>
      )}
      {kind === "admin" && (
        <p>
          {userName} получит доступ ко всей админ-панели: карточкам пользователей, логам, бэкапам и ручным действиям.
          Назначение попадёт в журнал, снять права можно в разделе «Администраторы».
        </p>
      )}
      {kind === "unblock" && <p>{userName} снова сможет войти. Старые сессии не вернутся, нужно войти заново.</p>}
      {limits && (
        <Field
          label={limits.label}
          hint={`От ${limits.min} до ${limits.max}`}
          error={amount !== "" && !amountValid ? `Целое число от ${limits.min} до ${limits.max}` : undefined}
        >
          {(control) => (
            <Input
              {...control}
              type="number"
              inputMode="numeric"
              min={limits.min}
              max={limits.max}
              step={1}
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
            />
          )}
        </Field>
      )}
      {needsReason && (
        <Field label="Причина" hint="Попадёт в журнал действий. От 3 до 500 символов.">
          {(control) => (
            <textarea
              {...control}
              className={`input ${styles.reason}`}
              rows={3}
              maxLength={500}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          )}
        </Field>
      )}
      {action.isError && (
        <p className={shared.alert} role="alert">
          {errorMessage(action.error, "Не получилось, попробуйте ещё раз")}
        </p>
      )}
      <div className={styles.actionButtons}>
        <Button variant="secondary" onClick={onClose}>
          Отмена
        </Button>
        <Button
          type="submit"
          variant={kind === "block" ? "danger" : "primary"}
          loading={action.isPending}
          disabled={!amountValid || !reasonValid}
        >
          {titles[kind]}
        </Button>
      </div>
    </form>
  );
}

export function UserActionDialog(props: DialogProps) {
  const { kind, onClose } = props;
  return (
    <Dialog open={kind !== null} onClose={onClose} title={kind ? titles[kind] : ""}>
      {kind && <ActionForm key={kind} {...props} kind={kind} />}
    </Dialog>
  );
}

type ButtonsProps = {
  userId: string;
  meId: string;
  isAdmin: boolean;
  blocked: boolean;
  onPick: (kind: ActionKind) => void;
};

export function UserActionButtons({ userId, meId, isAdmin, blocked, onPick }: ButtonsProps) {
  const canBlock = userId !== meId && !isAdmin;
  return (
    <>
      {!isAdmin && !blocked && (
        <Button size="sm" variant="secondary" onClick={() => onPick("admin")}>
          Назначить админом
        </Button>
      )}
      <Button size="sm" variant="secondary" onClick={() => onPick("hours")}>
        Начислить часы
      </Button>
      <Button size="sm" variant="secondary" onClick={() => onPick("subscription")}>
        Продлить подписку
      </Button>
      {blocked ? (
        <Button size="sm" variant="secondary" onClick={() => onPick("unblock")}>
          Разблокировать
        </Button>
      ) : (
        <Button
          size="sm"
          variant="ghost"
          disabled={!canBlock}
          title={canBlock ? undefined : "Себя и администраторов заблокировать нельзя"}
          onClick={() => onPick("block")}
        >
          Заблокировать
        </Button>
      )}
    </>
  );
}
