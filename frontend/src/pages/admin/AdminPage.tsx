import { lazy } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router";
import { NotFoundPage } from "../../app/NotFoundPage";
import { useMe } from "../../app/useMe";
import { Spinner } from "../../ui/Spinner";
import { AdminsSection } from "./AdminsSection";
import styles from "./AdminPage.module.css";
import { AuditSection } from "./AuditSection";

const AdminLogsPage = lazy(() =>
  import("./logs/AdminLogsPage").then((module) => ({ default: module.AdminLogsPage })),
);
const UsersSection = lazy(() =>
  import("./users/UsersSection").then((module) => ({ default: module.UsersSection })),
);
const UserCardSection = lazy(() =>
  import("./users/UserCardSection").then((module) => ({ default: module.UserCardSection })),
);
const StatsSection = lazy(() =>
  import("./users/StatsSection").then((module) => ({ default: module.StatsSection })),
);
const PromoSection = lazy(() =>
  import("./promo/PromoSection").then((module) => ({ default: module.PromoSection })),
);
const AdminBackupsPage = lazy(() =>
  import("./backups/AdminBackupsPage").then((module) => ({ default: module.AdminBackupsPage })),
);

const AdminAlertsPage = lazy(() =>
  import("./alerts/AdminAlertsPage").then((module) => ({ default: module.AdminAlertsPage })),
);

const AdminZoomerPage = lazy(() =>
  import("./zoomer/AdminZoomerPage").then((module) => ({ default: module.AdminZoomerPage })),
);

const sections = [
  { to: "/admin/users", label: "Пользователи" },
  { to: "/admin/stats", label: "Статистика" },
  { to: "/admin/promo", label: "Промокоды" },
  { to: "/admin/audit", label: "Журнал действий" },
  { to: "/admin/admins", label: "Администраторы" },
  { to: "/admin/logs", label: "Логи и ошибки" },
  { to: "/admin/backups", label: "Бэкапы" },
  { to: "/admin/alerts", label: "Алерты" },
  { to: "/admin/zoomer", label: "Ролики зумера" },
];

export function AdminPage() {
  const { data: me, isPending } = useMe();

  if (isPending) return <Spinner label="Загрузка" />;
  if (!me?.is_admin) return <NotFoundPage />;

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>Админ-панель</h1>
      <div className={styles.layout}>
        <nav className={styles.sections} aria-label="Разделы админ-панели">
          {sections.map((section) => (
            <NavLink
              key={section.to}
              to={section.to}
              className={({ isActive }) => (isActive ? `${styles.sectionLink} ${styles.sectionLinkActive}` : styles.sectionLink)}
            >
              {section.label}
            </NavLink>
          ))}
        </nav>
        <div className={styles.content}>
          <Routes>
            <Route index element={<Navigate to="/admin/audit" replace />} />
            <Route path="users" element={<UsersSection meId={me.id} />} />
            <Route path="users/:userId" element={<UserCardSection meId={me.id} />} />
            <Route path="stats" element={<StatsSection />} />
            <Route path="promo" element={<PromoSection />} />
            <Route path="audit" element={<AuditSection />} />
            <Route path="admins" element={<AdminsSection meId={me.id} />} />
            <Route path="logs" element={<AdminLogsPage />} />
            <Route path="backups" element={<AdminBackupsPage />} />
            <Route path="alerts" element={<AdminAlertsPage />} />
            <Route path="zoomer" element={<AdminZoomerPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </div>
      </div>
    </div>
  );
}
