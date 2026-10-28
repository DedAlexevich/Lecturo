import { lazy } from "react";
import type { RouteObject } from "react-router";
import { LoginPage } from "../pages/auth/LoginPage";
import { RegisterPage } from "../pages/auth/RegisterPage";
import { ResetPasswordPage } from "../pages/auth/ResetPasswordPage";
import { VkCallbackPage } from "../pages/auth/VkCallbackPage";
import { YandexCallbackPage } from "../pages/auth/YandexCallbackPage";
import { VerifyEmailPage } from "../pages/auth/VerifyEmailPage";
import { HomePage } from "../pages/home/HomePage";
import { CoursePage } from "../pages/course/CoursePage";

const LecturePage = lazy(() =>
  import("../pages/lecture/LecturePage").then((module) => ({ default: module.LecturePage })),
);
const LegalPage = lazy(() => import("../pages/legal/LegalPage").then((module) => ({ default: module.LegalPage })));
const AccountPage = lazy(() =>
  import("../pages/account/AccountPage").then((module) => ({ default: module.AccountPage })),
);
const LocalPage = lazy(() => import("../pages/local/LocalPage").then((module) => ({ default: module.LocalPage })));
const PublicSharePage = lazy(() =>
  import("../pages/public/PublicSharePage").then((module) => ({ default: module.PublicSharePage })),
);
const QuizPage = lazy(() => import("../features/quiz/QuizPage").then((module) => ({ default: module.QuizPage })));
const AdminPage = lazy(() => import("../pages/admin/AdminPage").then((module) => ({ default: module.AdminPage })));
const ExamSheetPage = lazy(() =>
  import("../features/exam-sheet/ExamSheetPage").then((module) => ({ default: module.ExamSheetPage })),
);

export const guestRoutes: RouteObject[] = [
  { path: "/login", element: <LoginPage /> },
  { path: "/register", element: <RegisterPage /> },
];

export const publicRoutes: RouteObject[] = [
  { path: "/local", element: <LocalPage /> },
  { path: "/legal/:slug", element: <LegalPage /> },
  { path: "/auth/vk", element: <VkCallbackPage /> },
  { path: "/auth/yandex", element: <YandexCallbackPage /> },
  { path: "/verify-email", element: <VerifyEmailPage /> },
  { path: "/reset-password", element: <ResetPasswordPage /> },
  ...(import.meta.env.DEV ? [{ path: "/ui", lazy: () => import("../ui/UiPage").then(({ UiPage }) => ({ Component: UiPage })) }] : []),
  { path: "/s/:token", element: <PublicSharePage /> },
  { path: "/s/:token/:lectureId", element: <PublicSharePage /> },
];

export const privateRoutes: RouteObject[] = [
  { path: "/", element: <HomePage /> },
  { path: "/lectures/:id", element: <LecturePage /> },
  { path: "/lectures/:id/quiz", element: <QuizPage /> },
  { path: "/courses/:id", element: <CoursePage /> },
  { path: "/courses/:id/exam-sheet", element: <ExamSheetPage /> },
  { path: "/account", element: <AccountPage /> },
  { path: "/admin/*", element: <AdminPage /> },
];
