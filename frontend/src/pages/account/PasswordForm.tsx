import { useState, type FormEvent } from "react";
import { Button } from "../../ui/Button";
import { Field } from "../../ui/Field";
import { Input } from "../../ui/Input";
import { useToast } from "../../ui/Toast";
import { validateNewPassword, validatePasswordConfirm } from "../auth/validation";
import styles from "./SettingsSection.module.css";
import { settingsError, useChangePassword } from "./settings";

export function PasswordForm() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [currentError, setCurrentError] = useState<string>();
  const [nextError, setNextError] = useState<string>();
  const [repeat, setRepeat] = useState("");
  const [repeatError, setRepeatError] = useState<string>();
  const change = useChangePassword();
  const toast = useToast();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const missingCurrent = current === "" ? "Введите текущий пароль" : undefined;
    const invalidNext = validateNewPassword(next);
    setCurrentError(missingCurrent);
    const mismatch = validatePasswordConfirm(next, repeat);
    setNextError(invalidNext);
    setRepeatError(mismatch);
    if (missingCurrent || invalidNext || mismatch) return;
    change.mutate(
      { current_password: current, new_password: next },
      {
        onSuccess: () => {
          setCurrent("");
          setNext("");
          setRepeat("");
          toast.show("Пароль изменён", "success");
        },
      },
    );
  };

  const failure = change.isError ? settingsError(change.error, "Неверный текущий пароль") : undefined;

  return (
    <form className={styles.form} onSubmit={submit} noValidate>
      <Field label="Текущий пароль" error={currentError}>
        {(control) => (
          <Input
            {...control}
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(event) => {
              setCurrent(event.target.value);
              setCurrentError(undefined);
              change.reset();
            }}
          />
        )}
      </Field>
      <Field label="Новый пароль" hint="От 8 до 128 символов" error={nextError}>
        {(control) => (
          <Input
            {...control}
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(event) => {
              setNext(event.target.value);
              setNextError(undefined);
              setRepeatError(undefined);
              change.reset();
            }}
          />
        )}
      </Field>
      <Field label="Повторите новый пароль" error={repeatError}>
        {(control) => (
          <Input
            {...control}
            type="password"
            autoComplete="new-password"
            value={repeat}
            onChange={(event) => {
              setRepeat(event.target.value);
              setRepeatError(undefined);
              change.reset();
            }}
          />
        )}
      </Field>
      {failure && (
        <p className={styles.alert} role="alert">
          {failure}
        </p>
      )}
      <div>
        <Button type="submit" loading={change.isPending}>
          Сменить пароль
        </Button>
      </div>
    </form>
  );
}
