import { useEffect, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router";

export function useUrlToken() {
  const [params] = useSearchParams();
  const [token] = useState(() => params.get("token"));
  const location = useLocation();
  const navigate = useNavigate();
  const hasToken = params.has("token");

  useEffect(() => {
    if (!hasToken) return;
    const rest = new URLSearchParams(location.search);
    rest.delete("token");
    const search = rest.toString();
    navigate(
      { pathname: location.pathname, search: search ? `?${search}` : "", hash: location.hash },
      { replace: true, state: location.state },
    );
  }, [hasToken, location.pathname, location.search, location.hash, location.state, navigate]);

  return token;
}
