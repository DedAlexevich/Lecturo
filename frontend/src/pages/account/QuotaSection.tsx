import { useId } from "react";
import { Progress } from "../../ui/Progress";
import styles from "./AccountPage.module.css";
import { useQuota, type Quota } from "./billing";
import { formatDuration } from "../../lib/duration";
import { formatDate, formatDateTime, formatRelative } from "./format";
import { SectionError, SectionLoading } from "./SectionState";

export function QuotaSection() {
  const titleId = useId();
  const { data: quota, isPending, isError, refetch } = useQuota();

  return (
    <section className={styles.panel} aria-labelledby={titleId}>
      <h2 id={titleId} className={styles.sectionTitle}>
        Лимит обработки
      </h2>
      {isPending && <SectionLoading label="Загружаем лимит" />}
      {isError && <SectionError message="Не удалось загрузить лимит." onRetry={() => refetch()} />}
      {quota && <QuotaDetails quota={quota} />}
    </section>
  );
}

function QuotaDetails({ quota }: { quota: Quota }) {
  const weeklyLeft = Math.max(0, quota.weekly_limit_sec - quota.weekly_used_sec);
  const available = weeklyLeft + quota.package_left_sec;
  const usedShare = quota.weekly_limit_sec > 0 ? (quota.weekly_used_sec / quota.weekly_limit_sec) * 100 : 100;

  return (
    <div className={styles.quota}>
      <div className={styles.quotaLead}>
        <p className={styles.figureLabel}>Доступно сейчас</p>
        <p className={styles.figure}>{formatDuration(available, "down")}</p>
        <p>
          Недельный лимит обновится {formatDateTime(quota.resets_at)}, {formatRelative(quota.resets_at)}.
        </p>
        {available === 0 && (
          <p className={styles.alert}>
            Часы закончились. Дождитесь обновления лимита, купите пакет или обработайте видео на устройстве.
          </p>
        )}
      </div>
      <dl className={styles.facts}>
        <div className={styles.fact}>
          <dt>На этой неделе</dt>
          <dd>
            <Progress
              label={`${formatDuration(quota.weekly_used_sec, "down")} из ${formatDuration(quota.weekly_limit_sec, "down")}`}
              value={usedShare}
              showValue={false}
            />
          </dd>
        </div>
        <div className={styles.fact}>
          <dt>Пакеты</dt>
          <dd>
            <span className={styles.factValue}>{formatDuration(quota.package_left_sec, "down")}</span>
            <span className={styles.muted}>Тратятся после недельного лимита и не сгорают</span>
          </dd>
        </div>
        <div className={styles.fact}>
          <dt>Тариф</dt>
          <dd>
            {quota.subscription_until ? (
              <>
                <span className={styles.factValue}>Подписка</span>
                <span className={styles.muted}>Действует до {formatDate(quota.subscription_until)}</span>
              </>
            ) : (
              <>
                <span className={styles.factValue}>Бесплатный</span>
                <span className={styles.muted}>Без квиза и памятки, видео хранится недолго</span>
              </>
            )}
          </dd>
        </div>
      </dl>
    </div>
  );
}
