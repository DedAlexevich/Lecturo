import { NavLink, Navigate, Route, Routes } from "react-router";
import { NotFoundPage } from "../../app/NotFoundPage";
import { useMe } from "../../app/useMe";
import { Spinner } from "../../ui/Spinner";
import { AdminsSection } from "./AdminsSection";
import styles from "./AdminPage.module.css";
import { AuditSection } from "./AuditSection";

const sections = [
  { to: "/admin/audit", label: "Журнал действий" },
  { to: "/admin/admins", label: "Администраторы" },
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
            <Route path="audit" element={<AuditSection />} />
            <Route path="admins" element={<AdminsSection meId={me.id} />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </div>
      </div>
    </div>
  );
}
