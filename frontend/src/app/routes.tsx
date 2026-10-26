import type { RouteObject } from "react-router";
import { LoginPage } from "../pages/auth/LoginPage";
import { LegalPage } from "../pages/legal/LegalPage";
import { RegisterPage } from "../pages/auth/RegisterPage";
import { ResetPasswordPage } from "../pages/auth/ResetPasswordPage";
import { VerifyEmailPage } from "../pages/auth/VerifyEmailPage";
import { UiPage } from "../ui/UiPage";
import { EmptyPage } from "./EmptyPage";

export const guestRoutes: RouteObject[] = [
  { path: "/login", element: <LoginPage /> },
  { path: "/register", element: <RegisterPage /> },
];

export const publicRoutes: RouteObject[] = [
  { path: "/legal/:slug", element: <LegalPage /> },
  { path: "/verify-email", element: <VerifyEmailPage /> },
  { path: "/reset-password", element: <ResetPasswordPage /> },
  { path: "/ui", element: <UiPage /> },
];

export const privateRoutes: RouteObject[] = [
  { path: "/", element: <EmptyPage title="Лекции" /> },
  { path: "/lectures/:id", element: <EmptyPage title="Лекция" /> },
  { path: "/courses/:id", element: <EmptyPage title="Курс" /> },
  { path: "/account", element: <EmptyPage title="Кабинет" /> },
];
