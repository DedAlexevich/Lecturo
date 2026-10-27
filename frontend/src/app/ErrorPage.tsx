import { isRouteErrorResponse, useRouteError } from "react-router";
import { Button } from "../ui/Button";
import { Logo } from "../ui/Logo";
import styles from "./ErrorPage.module.css";

export function ErrorPage() {
  const error = useRouteError();
  const notFound = isRouteErrorResponse(error) && error.status === 404;

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <a href="/" className={styles.logo}>
          <Logo />
        </a>
      </header>
      <main className={styles.main}>
        <h1 className={styles.title}>{notFound ? "Страница не найдена" : "Что-то пошло не так"}</h1>
        <p className={styles.text}>
          {notFound
            ? "Возможно, ссылка устарела или в адресе опечатка."
            : "Страница не смогла открыться. Обновите её, а если ошибка повторится, вернитесь на главную."}
        </p>
        <div className={styles.actions}>
          <Button onClick={() => window.location.reload()}>Обновить</Button>
          <Button variant="secondary" onClick={() => window.location.assign("/")}>
            На главную
          </Button>
        </div>
      </main>
    </div>
  );
}
