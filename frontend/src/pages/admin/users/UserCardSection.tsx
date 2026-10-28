import { useId, useState } from "react";
import { Link, useParams } from "react-router";
import { NotFoundPage } from "../../../app/NotFoundPage";
import { ApiError } from "../../../app/queryClient";
import { Button } from "../../../ui/Button";
import { Spinner } from "../../../ui/Spinner";
import { formatDuration } from "../../../lib/duration";
import { formatDate, formatDateTime, formatRubles, formatShortDate } from "../../account/format";
import shared from "../AdminPage.module.css";
import { useUserCard, type UserCard } from "./api";
import { formatHours, lectureStatusLabels, paymentStatusLabels, providerLabels, sourceLabels } from "./format";
import { UserActionButtons, UserActionDialog, type ActionKind } from "./UserActionDialog";
import styles from "./Users.module.css";

const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function userName(card: UserCard) {
  return card.display_name.trim() || card.email || "Без имени";
}

function consentLine(acceptedAt: string | null, revision: string | null) {
  if (!acceptedAt) return <span className={shared.muted}>Не дано</span>;
  return (
    <>
      {formatDate(acceptedAt)}
      {revision && <span className={styles.factNote}>редакция от {formatShortDate(revision)}</span>}
    </>
  );
}

function PlanBlock({ card }: { card: UserCard }) {
  const { quota } = card;
  const used = Math.min(quota.weekly_used_sec, quota.weekly_limit_sec);
  const share = quota.weekly_limit_sec > 0 ? used / quota.weekly_limit_sec : 0;

  return (
    <div className={styles.block}>
      <h3 className={styles.blockTitle}>Тариф и лимиты</h3>
      <p className={styles.plan}>
        {quota.subscription_until ? `Подписка до ${formatDate(quota.subscription_until)}` : "Бесплатный тариф"}
      </p>
      <div className={styles.meter}>
        <div className={styles.meterHead}>
          <span>Неделя</span>
          <span className={styles.figure}>
            {formatDuration(quota.weekly_used_sec)} из {formatDuration(quota.weekly_limit_sec)}
          </span>
        </div>
        <div
          className={styles.meterTrack}
          role="meter"
          aria-label="Израсходовано за неделю"
          aria-valuemin={0}
          aria-valuemax={quota.weekly_limit_sec}
          aria-valuenow={used}
        >
          {share > 0 && <div className={styles.meterFill} style={{ width: `${share * 100}%` }} />}
        </div>
        <p className={styles.factNote}>Сброс {formatDateTime(quota.resets_at)}</p>
      </div>
      <dl className={styles.facts}>
        <dt>Остаток пакетов</dt>
        <dd className={styles.figure}>{quota.package_left_sec > 0 ? formatHours(quota.package_left_sec) : "Нет"}</dd>
        <dt>Доступно сейчас</dt>
        <dd className={styles.figure}>
          {formatDuration(Math.max(quota.weekly_limit_sec - quota.weekly_used_sec, 0) + quota.package_left_sec)}
        </dd>
      </dl>
    </div>
  );
}

function AccountBlock({ card }: { card: UserCard }) {
  return (
    <div className={styles.block}>
      <h3 className={styles.blockTitle}>Аккаунт</h3>
      <dl className={styles.facts}>
        <dt>Регистрация</dt>
        <dd>{formatDate(card.created_at)}</dd>
        <dt>Почта</dt>
        <dd>
          {card.email ?? <span className={shared.muted}>Не указана</span>}
          {card.email && <span className={styles.factNote}>{card.email_verified ? "подтверждена" : "не подтверждена"}</span>}
        </dd>
        <dt>Способы входа</dt>
        <dd>
          {card.identities.length === 0 && <span className={shared.muted}>Нет</span>}
          {card.identities.map((identity) => (
            <span key={identity.provider} className={styles.factLine}>
              {providerLabels[identity.provider]}
              <span className={styles.factNote}>с {formatShortDate(identity.created_at)}</span>
            </span>
          ))}
        </dd>
      </dl>
    </div>
  );
}

function ConsentsBlock({ card }: { card: UserCard }) {
  const { consents } = card;
  return (
    <div className={styles.block}>
      <h3 className={styles.blockTitle}>Согласия</h3>
      <dl className={styles.facts}>
        <dt>Соглашение</dt>
        <dd>{consentLine(consents.terms_accepted_at, consents.terms_revision)}</dd>
        <dt>Персональные данные</dt>
        <dd>{consentLine(consents.personal_data_accepted_at, consents.personal_data_revision)}</dd>
        <dt>Передача в ИИ-сервисы</dt>
        <dd>{consentLine(consents.ai_transfer_accepted_at, consents.ai_transfer_revision)}</dd>
      </dl>
    </div>
  );
}

function PaymentsBlock({ card }: { card: UserCard }) {
  return (
    <div className={`${styles.block} ${styles.wide}`}>
      <h3 className={styles.blockTitle}>Платежи</h3>
      {card.payments.length === 0 ? (
        <p className={shared.muted}>Платежей не было.</p>
      ) : (
        <table className={styles.dataTable}>
          <thead>
            <tr>
              <th scope="col">Когда</th>
              <th scope="col">Что</th>
              <th scope="col">Статус</th>
              <th scope="col" className={styles.numeric}>
                Сумма
              </th>
            </tr>
          </thead>
          <tbody>
            {card.payments.map((payment) => (
              <tr key={payment.id}>
                <td className={shared.when}>{formatShortDate(payment.paid_at ?? payment.created_at)}</td>
                <td>{payment.kind === "subscription" ? "Подписка" : `Пакет ${payment.product_code.replace("hours_", "")} ч`}</td>
                <td>
                  <span className={payment.status === "succeeded" ? undefined : shared.muted}>
                    {paymentStatusLabels[payment.status]}
                  </span>
                </td>
                <td className={styles.numeric}>{formatRubles(payment.amount_kopecks / 100)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function LecturesBlock({ card }: { card: UserCard }) {
  const { lectures } = card;
  const counts = Object.entries(lectures.by_status) as [keyof typeof lectureStatusLabels, number][];

  return (
    <div className={`${styles.block} ${styles.wide}`}>
      <div className={styles.blockHead}>
        <h3 className={styles.blockTitle}>Лекции</h3>
        <p className={shared.muted}>Всего: {lectures.total}</p>
      </div>
      {lectures.total === 0 ? (
        <p className={shared.muted}>Лекций пока нет.</p>
      ) : (
        <>
          <ul className={styles.statusCounts}>
            {counts.map(([status, count]) => (
              <li key={status} className={status === "failed" ? styles.statusFailed : undefined}>
                {lectureStatusLabels[status]} <span className={styles.figure}>{count}</span>
              </li>
            ))}
          </ul>
          <table className={styles.dataTable}>
            <caption className={styles.caption}>Последние {lectures.recent.length}, без названий</caption>
            <thead>
              <tr>
                <th scope="col">Добавлена</th>
                <th scope="col">Источник</th>
                <th scope="col">Статус</th>
                <th scope="col" className={styles.numeric}>
                  Длительность
                </th>
              </tr>
            </thead>
            <tbody>
              {lectures.recent.map((lecture) => (
                <tr key={lecture.id}>
                  <td className={shared.when}>{formatShortDate(lecture.created_at)}</td>
                  <td>{sourceLabels[lecture.source_type]}</td>
                  <td className={lecture.status === "failed" ? styles.statusFailed : undefined}>
                    {lectureStatusLabels[lecture.status]}
                  </td>
                  <td className={styles.numeric}>
                    {lecture.duration_sec === null ? "—" : formatDuration(lecture.duration_sec)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

function Card({ card, meId }: { card: UserCard; meId: string }) {
  const titleId = useId();
  const [action, setAction] = useState<ActionKind | null>(null);
  const blocked = card.blocked_at !== null;

  return (
    <section className={shared.panel} aria-labelledby={titleId}>
      <Link className={styles.back} to="/admin/users">
        Назад к поиску
      </Link>
      <div className={styles.cardHead}>
        <div className={styles.identity}>
          <h2 id={titleId} className={shared.panelTitle}>
            {userName(card)}
          </h2>
          <p className={shared.muted}>
            {card.is_admin ? "Администратор · " : ""}
            {blocked ? "Заблокирован" : "Активен"}
          </p>
        </div>
        <div className={styles.cardActions}>
          <UserActionButtons
            userId={card.id}
            meId={meId}
            isAdmin={card.is_admin}
            blocked={blocked}
            onPick={setAction}
          />
        </div>
      </div>
      {blocked && card.blocked_at && (
        <p className={styles.blockedNote} role="status">
          Заблокирован {formatDateTime(card.blocked_at)}. Причина: {card.blocked_reason || "не указана"}
        </p>
      )}
      <div className={styles.blocks}>
        <PlanBlock card={card} />
        <AccountBlock card={card} />
        <ConsentsBlock card={card} />
        <PaymentsBlock card={card} />
        <LecturesBlock card={card} />
      </div>
      <UserActionDialog userId={card.id} userName={userName(card)} kind={action} onClose={() => setAction(null)} />
    </section>
  );
}

function LoadedCard({ userId, meId }: { userId: string; meId: string }) {
  const { data, isPending, isError, error, refetch } = useUserCard(userId);

  if (isPending) {
    return (
      <div className={shared.state}>
        <Spinner label="Загружаем карточку" />
      </div>
    );
  }
  if (isError) {
    if (error instanceof ApiError && error.status === 404) {
      return (
        <section className={shared.panel}>
          <Link className={styles.back} to="/admin/users">
            Назад к поиску
          </Link>
          <p className={shared.empty}>Такого пользователя нет. Возможно, он удалил аккаунт.</p>
        </section>
      );
    }
    return (
      <div className={shared.state} role="alert">
        <p>Не удалось загрузить карточку.</p>
        <Button variant="secondary" size="sm" onClick={() => refetch()}>
          Повторить
        </Button>
      </div>
    );
  }
  return <Card card={data} meId={meId} />;
}

export function UserCardSection({ meId }: { meId: string }) {
  const { userId = "" } = useParams();
  if (!uuidPattern.test(userId)) return <NotFoundPage />;
  return <LoadedCard key={userId} userId={userId} meId={meId} />;
}
