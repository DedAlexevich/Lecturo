import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { ApiError } from "./queryClient";
import { useToken } from "./session";

export const meQueryKey = ["me"] as const;

export function useMe() {
  const token = useToken();
  return useQuery({
    queryKey: meQueryKey,
    enabled: token !== null,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/me");
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });
}
