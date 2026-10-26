import type { RouteObject } from "react-router";
import { UiPage } from "../ui/UiPage";
import { EmptyPage } from "./EmptyPage";

export const guestRoutes: RouteObject[] = [
  { path: "/login", element: <EmptyPage title="Вход" /> },
];

export const publicRoutes: RouteObject[] = [
  { path: "/legal/:slug", element: <EmptyPage title="Документ" /> },
  { path: "/ui", element: <UiPage /> },
];

export const privateRoutes: RouteObject[] = [
  { path: "/", element: <EmptyPage title="Лекции" /> },
  { path: "/lectures/:id", element: <EmptyPage title="Лекция" /> },
  { path: "/courses/:id", element: <EmptyPage title="Курс" /> },
  { path: "/account", element: <EmptyPage title="Кабинет" /> },
];
