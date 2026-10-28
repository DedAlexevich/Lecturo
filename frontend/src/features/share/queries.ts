import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { detailOf } from "../../api/errors";
import type { components } from "../../api/schema";
import { ApiError } from "../../app/queryClient";

export type Share = components["schemas"]["ShareOut"];
export type ShareTarget = { lectureId: string } | { courseId: string };

const sharesKey = ["shares"] as const;

export function matchesTarget(share: Share, target: ShareTarget) {
  return "lectureId" in target ? share.lecture_id === target.lectureId : share.course_id === target.courseId;
}

export function useShares() {
  return useQuery({
    queryKey: sharesKey,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/shares");
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });
}

export function useCreateShare(target: ShareTarget) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const body = "lectureId" in target ? { lecture_id: target.lectureId } : { course_id: target.courseId };
      const { data, error, response } = await api.POST("/api/v1/shares", { body });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
    onSuccess: (share) => {
      client.setQueryData<Share[]>(sharesKey, (current) => [share, ...(current ?? [])]);
    },
  });
}

export function useRevokeShare() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (token: string) => {
      const { error, response } = await api.DELETE("/api/v1/shares/{token}", {
        params: { path: { token } },
      });
      if (!response.ok && response.status !== 404) throw new ApiError(response.status, error);
      return token;
    },
    onSuccess: (token) => {
      client.setQueryData<Share[]>(sharesKey, (current) => current?.filter((share) => share.token !== token));
    },
  });
}

export function errorDetail(error: unknown) {
  if (!(error instanceof ApiError)) return null;
  const detail = detailOf(error.body);
  return typeof detail === "string" ? detail : null;
}
