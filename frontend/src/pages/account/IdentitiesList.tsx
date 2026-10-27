import { useCallback, useState, type FormEvent } from "react";
import { Button } from "../../ui/Button";
import { Dialog } from "../../ui/Dialog";
import { Field } from "../../ui/Field";
import { Input } from "../../ui/Input";
import { useToast } from "../../ui/Toast";
import { TelegramButton, telegramEnabled } from "../auth/TelegramButton";
import { VkButton } from "../auth/VkButton";
import { useVkEnabled } from "../auth/vk";
import { validateEmail, validateNewPassword } from "../auth/validation";
import { formatDate } from "./format";
import styles from "./SettingsSection.module.css";
import { settingsError, useLinkEmail, useLinkTelegram, useUnlink, type Me, type Provider, type TelegramUser } from "./settings";

const providerNames: Record<Provider, string> = { telegram: "Telegram", email: "Почта", vk: "VK", yandex: "Яндекс" };

const unlinkNotes: Record<Provider, string> = {
  telegram: "Войти через Telegram будет нельзя, пока вы не привяжете его снова.",
  email: "Почта и пароль будут удалены, войти по ним будет нельзя.",
  vk: "Войти через VK будет нельзя, пока вы не привяжете его снова.",
  yandex: "Войти через Яндекс будет нельзя, пока вы не привяжете его снова.",
};

export function IdentitiesList({ me }: { me: Me }) {
  const [confirming, setConfirming] = useState<Provider | null>(null);
  const unlink = useUnlink();
  const toast = useToast();
  const { reset } = unlink;
  const linked = (provider: Provider) => me.identities.find((identity) => identity.provider === provider);
  const vkEnabled = useVkEnabled();
  const providers: Provider[] = [
    "telegram",
    "email",
    ...(vkEnabled || linked("vk") ? (["vk"] as const) : []),
    ...me.identities
      .map((identity) => identity.provider)
      .filter((provider) => provider !== "telegram" && provider !== "email" && provider !== "vk"),
  ];
  const onlyOne = me.identities.length <= 1;

  const close = useCallback(() => {
    setConfirming(null);
    reset();
  }, [reset]);

  const confirmUnlink = () => {
    if (!confirming) return;
    unlink.mutate(confirming, {
      onSuccess: () => {
        toast.show(`${providerNames[confirming]} отвязан`, "success");
        close();
      },
    });
  };

  return (
    <>
      <ul className={styles.identities}>
        {providers.map((provider) => {
          const identity = linked(provider);
          return (
            <li key={provider} className={styles.identity}>
              <div className={styles.identityInfo}>
                <span className={styles.identityName}>{providerNames[provider]}</span>
                <span className={styles.muted}>{identity ? identityNote(me, provider, identity.created_at) : "Не привязан"}</span>
              </div>
              {identity ? (
                <div className={styles.identityAction}>
                  <Button variant="secondary" size="sm" disabled={onlyOne} onClick={() => setConfirming(provider)}>
                    Отвязать
                  </Button>
                  {onlyOne && <span className={styles.muted}>Единственный способ входа</span>}
                </div>
              ) : provider === "telegram" ? (
                <LinkTelegram />
              ) : provider === "vk" ? (
                <LinkVk />
              ) : (
                <LinkEmail />
              )}
            </li>
          );
        })}
      </ul>
      <Dialog
        open={confirming !== null}
        onClose={close}
        title={confirming ? `Отвязать ${providerNames[confirming].toLowerCase()}?` : ""}
        actions={
          <>
            <Button variant="secondary" onClick={close}>
              Отмена
            </Button>
            <Button variant="danger" loading={unlink.isPending} onClick={confirmUnlink}>
              Отвязать
            </Button>
          </>
        }
      >
        {confirming && <p>{unlinkNotes[confirming]}</p>}
        {unlink.isError && (
          <p className={styles.alert} role="alert">
            {settingsError(unlink.error)}
          </p>
        )}
      </Dialog>
    </>
  );
}

function identityNote(me: Me, provider: Provider, createdAt: string) {
  if (provider === "email" && me.email) return `${me.email}${me.email_verified ? "" : ", не подтверждена"}`;
  return `Привязан ${formatDate(createdAt)}`;
}

function LinkTelegram() {
  const link = useLinkTelegram();
  const toast = useToast();
  const { mutate } = link;

  const onAuth = useCallback(
    (user: TelegramUser) => mutate(user, { onSuccess: () => toast.show("Telegram привязан", "success") }),
    [mutate, toast],
  );

  if (!telegramEnabled) return <span className={styles.muted}>Сейчас недоступно</span>;

  return (
    <div className={styles.identityAction}>
      <TelegramButton onAuth={onAuth} />
      {link.isError && (
        <p className={styles.alert} role="alert">
          {settingsError(link.error)}
        </p>
      )}
    </div>
  );
}

function LinkVk() {
  const [error, setError] = useState<unknown>();
  return (
    <div className={styles.identityAction}>
      <VkButton flow={{ mode: "link", redirect: "/account" }} label="Привязать" size="sm" onError={setError} />
      {error !== undefined && (
        <p className={styles.alert} role="alert">
          {settingsError(error)}
        </p>
      )}
    </div>
  );
}

function LinkEmail() {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<{ email?: string; password?: string }>({});
  const link = useLinkEmail();
  const toast = useToast();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const next = { email: validateEmail(email), password: validateNewPassword(password) };
    setErrors(next);
    if (next.email || next.password) return;
    link.mutate(
      { email: email.trim(), password },
      { onSuccess: () => toast.show("Почта привязана", "success") },
    );
  };

  if (!open) {
    return (
      <Button variant="secondary" size="sm" onClick={() => setOpen(true)}>
        Привязать
      </Button>
    );
  }

  return (
    <form className={styles.linkForm} onSubmit={submit} noValidate>
      <Field label="Адрес почты" error={errors.email}>
        {(control) => (
          <Input
            {...control}
            type="email"
            autoComplete="email"
            value={email}
            onChange={(event) => {
              setEmail(event.target.value);
              link.reset();
            }}
          />
        )}
      </Field>
      <Field label="Пароль для входа по почте" hint="От 8 до 128 символов" error={errors.password}>
        {(control) => (
          <Input
            {...control}
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(event) => {
              setPassword(event.target.value);
              link.reset();
            }}
          />
        )}
      </Field>
      {link.isError && (
        <p className={styles.alert} role="alert">
          {settingsError(link.error)}
        </p>
      )}
      <div className={styles.actions}>
        <Button type="submit" size="sm" loading={link.isPending}>
          Привязать
        </Button>
        <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
          Отмена
        </Button>
      </div>
    </form>
  );
}
