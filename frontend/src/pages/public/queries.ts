import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { ApiError } from "../../app/queryClient";

export async function fetchPublicShare(token: string) {
  const { data, error, response } = await api.GET("/api/v1/public/{token}", {
    params: { path: { token } },
  });
  if (data === undefined) throw new ApiError(response.status, error);
  return data;
}

export function usePublicShare(token: string) {
  return useQuery({
    queryKey: ["public", token],
    queryFn: () => fetchPublicShare(token),
  });
}

export async function fetchPublicCourseLecture(token: string, lectureId: string) {
  const { data, error, response } = await api.GET("/api/v1/public/{token}/lectures/{lecture_id}", {
    params: { path: { token, lecture_id: lectureId } },
  });
  if (data === undefined) throw new ApiError(response.status, error);
  return data;
}

export function usePublicCourseLecture(token: string, lectureId: string) {
  return useQuery({
    queryKey: ["public", token, lectureId],
    queryFn: () => fetchPublicCourseLecture(token, lectureId),
  });
}

export function useComplaint(token: string, lectureId: string) {
  return useMutation({
    mutationFn: async (reason: string) => {
      const { error, response } = await api.POST("/api/v1/public/{token}/complaints", {
        params: { path: { token } },
        body: { reason, lecture_id: lectureId },
      });
      if (!response.ok) throw new ApiError(response.status, error);
    },
  });
}
