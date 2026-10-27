import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { components } from "../../api/schema";
import { ApiError } from "../../app/queryClient";

type LectureStatus = components["schemas"]["LectureStatus"];

const STATUS_POLL_INTERVAL_MS = 3000;
const pendingStatuses = new Set<LectureStatus>(["queued", "waiting_quota", "processing"]);

export function isPending(status: LectureStatus) {
  return pendingStatuses.has(status);
}

export function lectureQueryKey(id: string) {
  return ["lectures", id] as const;
}

function lectureStatusQueryKey(id: string) {
  return ["lecture-status", id] as const;
}

export function useLecture(id: string) {
  return useQuery({
    queryKey: lectureQueryKey(id),
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/lectures/{lecture_id}", {
        params: { path: { lecture_id: id } },
      });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });
}

export function useLectureStatus(id: string, lectureStatus: LectureStatus | undefined) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: lectureStatusQueryKey(id),
    enabled: lectureStatus !== undefined && isPending(lectureStatus),
    refetchInterval: (current) =>
      !current.state.data || isPending(current.state.data.status) ? STATUS_POLL_INTERVAL_MS : false,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/lectures/{lecture_id}/status", {
        params: { path: { lecture_id: id } },
      });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });

  const polledStatus = query.data?.status;
  const polledDone = query.data?.steps.filter((step) => step.status === "done").length ?? 0;
  const seen = useRef<string | null>(null);

  useEffect(() => {
    if (polledStatus === undefined) return;
    const signature = `${polledStatus}:${polledDone}`;
    const previous = seen.current;
    seen.current = signature;
    if (previous === null || previous === signature) return;
    void queryClient.invalidateQueries({ queryKey: lectureQueryKey(id), exact: true });
  }, [polledStatus, polledDone, id, queryClient]);

  return query;
}

export function useRetryProcessing(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST("/api/v1/lectures/{lecture_id}/retry", {
        params: { path: { lecture_id: id } },
      });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
    onSuccess: (status) => {
      queryClient.setQueryData(lectureStatusQueryKey(id), status);
      return queryClient.invalidateQueries({ queryKey: lectureQueryKey(id), exact: true });
    },
  });
}
