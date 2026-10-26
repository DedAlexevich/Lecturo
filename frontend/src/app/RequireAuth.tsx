import { Navigate, Outlet, useLocation } from "react-router";
import { useToken } from "./session";

export function RequireAuth() {
  const token = useToken();
  const location = useLocation();

  if (token === null) return <Navigate to="/login" replace state={{ from: location }} />;
  return <Outlet />;
}
