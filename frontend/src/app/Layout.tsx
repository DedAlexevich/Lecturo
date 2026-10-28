import { LinkTelegramPrompt } from "../telegram/LinkTelegramPrompt";
import { TelegramBridge } from "../telegram/TelegramBridge";
import { useQuery } from "@tanstack/react-query";
import { Suspense } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router";
import { api } from "../api/client";
import { ApiError } from "./queryClient";
import styles from "./Layout.module.css";
import { signOut, useToken } from "./session";
import { useMe } from "./useMe";
import { CookieNotice } from "../features/consent/CookieNotice";
import { LegalUpdateNotice } from "../features/legal-updates/LegalUpdateNotice";
import { AddLectureDialog } from "../features/upload/AddLectureDialog";
import { QuotaDialog } from "../features/quota-dialog/QuotaDialog";
import { WaitingNotice } from "../features/quota-dialog/WaitingNotice";
import { Logo } from "../ui/Logo";
import { Spinner } from "../ui/Spinner";
import { ThemeToggle } from "../ui/ThemeToggle";

const navItems = [
  { to: "/", label: "Лекции" },
  { to: "/account", label: "Кабинет" },
  { to: "/local", label: "На устройстве" },
];

function Navigation({ className }: { className: string }) {
  return (
    <nav className={className}>
      {navItems.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end
          className={({ isActive }) => (isActive ? `${styles.navLink} ${styles.navLinkActive}` : styles.navLink)}
        >
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
}

function UserBlock() {
  const { data: me } = useMe();

  return (
    <div className={styles.user}>
      {me && <span className={styles.userName}>{me.display_name.trim() || me.email}</span>}
      <button type="button" className={styles.textButton} onClick={signOut}>
        Выйти
      </button>
    </div>
  );
}

function LegalFooter() {
  const { data: documents = [] } = useQuery({
    queryKey: ["legal"],
    staleTime: Infinity,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/legal");
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });

  return (
    <footer className={styles.footer}>
      <div className={styles.footerInner}>
        <ul className={styles.legalLinks}>
          {documents.map((document) => (
            <li key={document.slug}>
              <Link to={`/legal/${document.slug}`}>{document.title}</Link>
            </li>
          ))}
        </ul>
        <ThemeToggle />
      </div>
    </footer>
  );
}

export function Layout() {
  const signedIn = useToken() !== null;
  const onLoginPage = useLocation().pathname === "/login";

  return (
    <div className={signedIn ? `${styles.shell} ${styles.shellSigned}` : styles.shell}>
      {signedIn && (
        <aside className={styles.sidebar}>
          <Link to="/" className={styles.logo}>
            <Logo />
          </Link>
          <Navigation className={styles.sideNav} />
          <UserBlock />
        </aside>
      )}
      <div className={styles.column}>
        <header className={styles.header}>
          <Link to="/" className={styles.logo}>
            <Logo />
          </Link>
          {!signedIn && <Link to="/local" className={styles.textButton}>На устройстве</Link>}
          {!signedIn && !onLoginPage && (
            <Link to="/login" className={styles.textButton}>
              Войти
            </Link>
          )}
        </header>
        <main className={styles.main}>
          <TelegramBridge />
          <LegalUpdateNotice />
          {signedIn && <WaitingNotice />}
          <Suspense fallback={<Spinner label="Загрузка" />}>
            <Outlet />
          </Suspense>
        </main>
        <LegalFooter />
      </div>
      {signedIn && <Navigation className={styles.bottomNav} />}
      {signedIn && <AddLectureDialog />}
      {signedIn && <QuotaDialog />}
      {signedIn && <LinkTelegramPrompt />}
      <CookieNotice />
    </div>
  );
}
