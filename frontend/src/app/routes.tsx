import type { RouteObject } from "react-router";
import { LoginPage } from "../pages/auth/LoginPage";
import { LegalPage } from "../pages/legal/LegalPage";
import { RegisterPage } from "../pages/auth/RegisterPage";
import { ResetPasswordPage } from "../pages/auth/ResetPasswordPage";
import { VkCallbackPage } from "../pages/auth/VkCallbackPage";
import { YandexCallbackPage } from "../pages/auth/YandexCallbackPage";
import { VerifyEmailPage } from "../pages/auth/VerifyEmailPage";
import { LecturePage } from "../pages/lecture/LecturePage";
import { HomePage } from "../pages/home/HomePage";
import { UiPage } from "../ui/UiPage";
import { AccountPage } from "../pages/account/AccountPage";
import { LocalPage } from "../pages/local/LocalPage";
import { CoursePage } from "../pages/course/CoursePage";
import { PublicSharePage } from "../pages/public/PublicSharePage";
import { ExamSheetPage } from "../features/exam-sheet/ExamSheetPage";

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
  { path: "/ui", element: <UiPage /> },
  { path: "/s/:token", element: <PublicSharePage /> },
];

export const privateRoutes: RouteObject[] = [
  { path: "/", element: <HomePage /> },
  { path: "/lectures/:id", element: <LecturePage /> },
  { path: "/courses/:id", element: <CoursePage /> },
  { path: "/courses/:id/exam-sheet", element: <ExamSheetPage /> },
  { path: "/account", element: <AccountPage /> },
];
