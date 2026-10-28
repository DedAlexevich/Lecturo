import { createBrowserRouter } from "react-router";
import { ErrorPage } from "./ErrorPage";
import { Layout } from "./Layout";
import { NotFoundPage } from "./NotFoundPage";
import { GuestOnly, RequireAuth } from "./RequireAuth";
import { guestRoutes, privateRoutes, publicRoutes } from "./routes";

export const router = createBrowserRouter([
  {
    element: <Layout />,
    errorElement: <ErrorPage />,
    children: [
      ...publicRoutes,
      { element: <GuestOnly />, children: guestRoutes },
      { element: <RequireAuth />, children: privateRoutes },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);
