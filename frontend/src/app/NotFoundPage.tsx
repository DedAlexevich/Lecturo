import { Link } from "react-router";

export function NotFoundPage() {
  return (
    <>
      <h1>Страница не найдена</h1>
      <Link to="/">На главную</Link>
    </>
  );
}
