import { useId } from "react";
import { useMe } from "../../app/useMe";
import { AiTransferConsent } from "./AiTransferConsent";
import { DeleteAccount } from "./DeleteAccount";
import { IdentitiesList } from "./IdentitiesList";
import { NameForm } from "./NameForm";
import { PasswordForm } from "./PasswordForm";
import { SettingsRow } from "./SettingsRow";
import { SectionError, SectionLoading } from "./SectionState";
import styles from "./SettingsSection.module.css";

export function SettingsSection() {
  const titleId = useId();
  const { data: me, isPending, isError, refetch } = useMe();
  const hasPassword = me?.identities.some((identity) => identity.provider === "email") ?? false;

  return (
    <section className={styles.panel} aria-labelledby={titleId}>
      <h2 id={titleId} className={styles.sectionTitle}>
        Настройки аккаунта
      </h2>
      {isPending && <SectionLoading label="Загружаем настройки" />}
      {isError && <SectionError message="Не удалось загрузить настройки." onRetry={() => refetch()} />}
      {me && (
        <div className={styles.rows}>
          <SettingsRow title="Имя" note="Так вас видно в кабинете">
            <NameForm key={me.display_name} displayName={me.display_name} />
          </SettingsRow>
          <SettingsRow title="Способы входа" note="Нужен хотя бы один">
            <IdentitiesList me={me} />
          </SettingsRow>
          {hasPassword && (
            <SettingsRow title="Пароль" note="Для входа по почте">
              <PasswordForm />
            </SettingsRow>
          )}
          <SettingsRow title="Передача данных ИИ" note="Согласие на серверную обработку">
            <AiTransferConsent me={me} />
          </SettingsRow>
          <SettingsRow title="Удаление аккаунта" note="Действие нельзя отменить">
            <DeleteAccount hasPassword={hasPassword} />
          </SettingsRow>
        </div>
      )}
    </section>
  );
}
