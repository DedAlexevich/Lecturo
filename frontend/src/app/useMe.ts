import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useToken } from "./session";

export const meQueryKey = ["me"] as const;

export function useMe() {
  const token = useToken();
  return useQuery({
    queryKey: meQueryKey,
    enabled: token !== null,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/v1/me");
      if (error) throw error;
      return data;
    },
  });
}
