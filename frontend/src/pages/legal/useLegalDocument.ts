import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { ApiError } from "../../app/queryClient";

export function useLegalDocument(slug: string) {
  return useQuery({
    queryKey: ["legal", slug],
    staleTime: Infinity,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/legal/{slug}", { params: { path: { slug } } });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });
}
