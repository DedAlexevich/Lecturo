import { createBrowserRouter } from "react-router";
import { Layout } from "./Layout";
import { NotFoundPage } from "./NotFoundPage";
import { RequireAuth } from "./RequireAuth";
import { privateRoutes, publicRoutes } from "./routes";

export const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      ...publicRoutes,
      { element: <RequireAuth />, children: privateRoutes },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);
