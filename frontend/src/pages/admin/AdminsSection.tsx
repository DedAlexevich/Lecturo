import { useQueryClient } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { meQueryKey } from "../../app/useMe";
import { Button } from "../../ui/Button";
import { Dialog } from "../../ui/Dialog";
import { Field } from "../../ui/Field";
import { Input } from "../../ui/Input";
import { Spinner } from "../../ui/Spinner";
import { useToast } from "../../ui/Toast";
import styles from "./AdminPage.module.css";
import { errorMessage, useAdmins, useGrantAdmin, useRevokeAdmin, type Admin } from "./api";

function adminName(admin: Admin) {
  return admin.display_name.trim() || admin.email || "Без имени";
}

function GrantForm() {
  const [identifier, setIdentifier] = useState("");
  const grant = useGrantAdmin();
  const toast = useToast();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const value = identifier.trim();
    if (!value) return;
    grant.mutate(value, {
      onSuccess: (admin) => {
        setIdentifier("");
        toast.show(`${adminName(admin)} теперь администратор`, "success");
      },
    });
  };

  return (
    <form className={styles.grantForm} onSubmit={submit}>
      <Field
        label="Назначить администратора"
        hint="Почта или числовой Telegram id. Пользователь должен быть уже зарегистрирован."
        error={grant.isError ? errorMessage(grant.error, "Не удалось назначить, попробуйте ещё раз") : undefined}
      >
        {(control) => (
          <Input
            {...control}
            value={identifier}
            autoComplete="off"
            spellCheck={false}
            maxLength={320}
            onChange={(event) => {
              setIdentifier(event.target.value);
              if (grant.isError) grant.reset();
            }}
          />
        )}
      </Field>
      <Button type="submit" loading={grant.isPending} disabled={!identifier.trim()}>
        Назначить
      </Button>
    </form>
  );
}

function RevokeDialog({ admin, isSelf, onClose }: { admin: Admin | null; isSelf: boolean; onClose: () => void }) {
  const revoke = useRevokeAdmin();
  const toast = useToast();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const close = () => {
    revoke.reset();
    onClose();
  };

  const confirm = () => {
    if (!admin) return;
    revoke.mutate(admin.id, {
      onSuccess: async () => {
        close();
        if (isSelf) {
          await queryClient.invalidateQueries({ queryKey: meQueryKey });
          navigate("/", { replace: true });
          return;
        }
        toast.show(`${adminName(admin)} больше не администратор`, "success");
      },
    });
  };

  return (
    <Dialog
      open={admin !== null}
      onClose={close}
      title="Снять права администратора?"
      actions={
        <>
          <Button variant="secondary" onClick={close}>
            Отмена
          </Button>
          <Button variant="danger" loading={revoke.isPending} onClick={confirm}>
            Снять
          </Button>
        </>
      }
    >
      <p>
        {isSelf
          ? "Вы сразу потеряете доступ к админ-панели. Вернуть права сможет другой администратор."
          : `${admin ? adminName(admin) : ""} сразу потеряет доступ к админ-панели.`}
      </p>
      {revoke.isError && (
        <p className={styles.alert} role="alert">
          {errorMessage(revoke.error, "Не удалось снять права, попробуйте ещё раз")}
        </p>
      )}
    </Dialog>
  );
}

export function AdminsSection({ meId }: { meId: string }) {
  const titleId = useId();
  const { data: admins, isPending, isError, refetch } = useAdmins();
  const [revoking, setRevoking] = useState<Admin | null>(null);
  const lastAdmin = admins?.length === 1;

  return (
    <section className={styles.panel} aria-labelledby={titleId}>
      <div className={styles.panelHead}>
        <h2 id={titleId} className={styles.panelTitle}>
          Администраторы
        </h2>
        {admins && <p className={styles.muted}>Всего: {admins.length}</p>}
      </div>
      {isPending && (
        <div className={styles.state}>
          <Spinner label="Загружаем администраторов" />
        </div>
      )}
      {isError && (
        <div className={styles.state} role="alert">
          <p>Не удалось загрузить администраторов.</p>
          <Button variant="secondary" size="sm" onClick={() => refetch()}>
            Повторить
          </Button>
        </div>
      )}
      {admins && (
        <ul className={styles.admins}>
          {admins.map((admin) => (
            <li key={admin.id} className={styles.admin}>
              <div className={styles.adminInfo}>
                <span className={styles.adminName}>
                  {adminName(admin)}
                  {admin.id === meId && <span className={styles.selfMark}>Вы</span>}
                </span>
                {admin.email && admin.email !== adminName(admin) && <span className={styles.subline}>{admin.email}</span>}
              </div>
              <Button
                variant="ghost"
                size="sm"
                disabled={lastAdmin}
                title={lastAdmin ? "Последнего администратора снять нельзя" : undefined}
                onClick={() => setRevoking(admin)}
              >
                Снять
              </Button>
            </li>
          ))}
        </ul>
      )}
      {lastAdmin && <p className={styles.muted}>Последнего администратора снять нельзя. Сначала назначьте ещё одного.</p>}
      <GrantForm />
      <RevokeDialog admin={revoking} isSelf={revoking?.id === meId} onClose={() => setRevoking(null)} />
    </section>
  );
}
