import { Navigate, Outlet, useLocation } from "react-router";
import { redirectTarget } from "../pages/auth/redirect";
import { useToken } from "./session";

export function RequireAuth() {
  const token = useToken();
  const location = useLocation();

  if (token === null) {
    const hash = location.hash.includes("tgWebAppData") ? "" : location.hash;
    return <Navigate to="/login" replace state={{ from: { ...location, hash } }} />;
  }
  return <Outlet />;
}

export function GuestOnly() {
  const token = useToken();
  const location = useLocation();
  return token === null ? <Outlet /> : <Navigate to={redirectTarget(location.state)} replace />;
}
