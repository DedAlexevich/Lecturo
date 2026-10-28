import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { ApiError } from "./queryClient";
import styles from "./MaintenanceNotice.module.css";

export function MaintenanceNotice() {
  const { data } = useQuery({
    queryKey: ["maintenance"],
    refetchInterval: 20_000,
    refetchOnWindowFocus: true,
    retry: false,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/maintenance");
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });

  if (!data?.active) return null;

  return (
    <div className={styles.notice} role="alert">
      <strong>Идут работы</strong>
      <span>{data.message}. Страница обновится сама.</span>
    </div>
  );
}
