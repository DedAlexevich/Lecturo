import { useState, type FormEvent } from "react";
import { Button } from "../../ui/Button";
import { Field } from "../../ui/Field";
import { Input } from "../../ui/Input";
import { useToast } from "../../ui/Toast";
import styles from "./SettingsSection.module.css";
import { settingsError, useRename } from "./settings";

export function NameForm({ displayName }: { displayName: string }) {
  const [value, setValue] = useState(displayName);
  const [invalid, setInvalid] = useState<string>();
  const rename = useRename();
  const toast = useToast();
  const name = value.trim();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (name === "") {
      setInvalid("Введите имя");
      return;
    }
    setInvalid(undefined);
    rename.mutate(name, {
      onSuccess: () => toast.show("Имя сохранено", "success"),
    });
  };

  const error = invalid ?? (rename.isError ? settingsError(rename.error) : undefined);

  return (
    <form className={styles.form} onSubmit={submit} noValidate>
      <Field label="Имя" error={error}>
        {(control) => (
          <Input
            {...control}
            value={value}
            maxLength={120}
            autoComplete="name"
            onChange={(event) => {
              setValue(event.target.value);
              setInvalid(undefined);
              rename.reset();
            }}
          />
        )}
      </Field>
      <div>
        <Button type="submit" loading={rename.isPending} disabled={name === displayName}>
          Сохранить
        </Button>
      </div>
    </form>
  );
}
