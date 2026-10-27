import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { ApiError } from "../../app/queryClient";

export function usePublicShare(token: string) {
  return useQuery({
    queryKey: ["public", token],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/public/{token}", {
        params: { path: { token } },
      });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });
}

export function useComplaint(token: string) {
  return useMutation({
    mutationFn: async (reason: string) => {
      const { error, response } = await api.POST("/api/v1/public/{token}/complaints", {
        params: { path: { token } },
        body: { reason },
      });
      if (!response.ok) throw new ApiError(response.status, error);
    },
  });
}
