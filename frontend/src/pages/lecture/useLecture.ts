import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { components } from "../../api/schema";
import { ApiError } from "../../app/queryClient";

type LectureStatus = components["schemas"]["LectureStatus"];
type Lecture = components["schemas"]["LectureDetail"];
type Step = components["schemas"]["StepOut"];

const STATUS_POLL_INTERVAL_MS = 3000;
const STATUS_POLL_MAX_INTERVAL_MS = 30000;
const STALLED_AFTER_FAILURES = 3;
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

export async function fetchLecture(id: string) {
  const { data, error, response } = await api.GET("/api/v1/lectures/{lecture_id}", {
    params: { path: { lecture_id: id } },
  });
  if (data === undefined) throw new ApiError(response.status, error);
  return data;
}

export function useLecture(id: string) {
  return useQuery({
    queryKey: lectureQueryKey(id),
    queryFn: () => fetchLecture(id),
  });
}

function signatureOf(status: LectureStatus, steps: Step[]) {
  return `${status}:${steps.filter((step) => step.status === "done").length}`;
}

export function useLectureStatus(id: string, lecture: Lecture | undefined) {
  const queryClient = useQueryClient();
  const failures = useRef(0);
  const query = useQuery({
    queryKey: lectureStatusQueryKey(id),
    enabled: lecture !== undefined && isPending(lecture.status),
    refetchInterval: (current) => {
      if (current.state.data && !isPending(current.state.data.status)) return false;
      if (failures.current === 0) return STATUS_POLL_INTERVAL_MS;
      return Math.min(STATUS_POLL_MAX_INTERVAL_MS, STATUS_POLL_INTERVAL_MS * 2 ** failures.current);
    },
    queryFn: async () => {
      try {
        const { data, error, response } = await api.GET("/api/v1/lectures/{lecture_id}/status", {
          params: { path: { lecture_id: id } },
        });
        if (data === undefined) throw new ApiError(response.status, error);
        failures.current = 0;
        return data;
      } catch (error) {
        failures.current += 1;
        throw error;
      }
    },
  });

  const polled = query.data ? signatureOf(query.data.status, query.data.steps) : null;
  const loaded = lecture ? signatureOf(lecture.status, lecture.steps) : null;
  const requested = useRef<string | null>(null);

  useEffect(() => {
    if (polled === null || loaded === null) return;
    if (polled === loaded || polled === requested.current) return;
    requested.current = polled;
    void queryClient.invalidateQueries({ queryKey: lectureQueryKey(id), exact: true });
  }, [polled, loaded, id, queryClient]);

  return { data: query.data, stalled: query.isError && failures.current >= STALLED_AFTER_FAILURES };
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
