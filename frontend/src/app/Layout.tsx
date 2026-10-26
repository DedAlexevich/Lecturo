import { useQuery } from "@tanstack/react-query";
import { Link, NavLink, Outlet } from "react-router";
import { api } from "../api/client";
import { ApiError } from "./queryClient";
import styles from "./Layout.module.css";
import { signOut, useToken } from "./session";
import { useMe } from "./useMe";

const navItems = [
  { to: "/", label: "Лекции" },
  { to: "/account", label: "Кабинет" },
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

function UserMenu() {
  const { data: me } = useMe();

  return (
    <>
      {me && <span className={styles.userName}>{me.display_name}</span>}
      <button type="button" className={styles.textButton} onClick={signOut}>
        Выйти
      </button>
    </>
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
      </div>
    </footer>
  );
}

export function Layout() {
  const signedIn = useToken() !== null;

  return (
    <div className={signedIn ? `${styles.shell} ${styles.withBottomNav}` : styles.shell}>
      <header className={styles.header}>
        <div className={styles.bar}>
          <Link to="/" className={styles.logo}>
            Lecturo
          </Link>
          {signedIn && <Navigation className={styles.topNav} />}
          <div className={styles.user}>
            {signedIn ? (
              <UserMenu />
            ) : (
              <Link to="/login" className={styles.textButton}>
                Войти
              </Link>
            )}
          </div>
        </div>
      </header>
      <main className={styles.main}>
        <Outlet />
      </main>
      <LegalFooter />
      {signedIn && <Navigation className={styles.bottomNav} />}
    </div>
  );
}
