import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { components } from "../../api/schema";
import { ApiError } from "../../app/queryClient";

export type Waiting = components["schemas"]["WaitingOut"];
export type WaitingLecture = components["schemas"]["WaitingLectureOut"];

export const waitingQueryKey = ["billing", "waiting"] as const;

const pollInterval = 20_000;

export async function fetchWaiting() {
  const { data, error, response } = await api.GET("/api/v1/billing/waiting");
  if (data === undefined) throw new ApiError(response.status, error);
  return data;
}

export function useWaiting() {
  return useQuery({
    queryKey: waitingQueryKey,
    queryFn: fetchWaiting,
    refetchInterval: pollInterval,
    refetchOnWindowFocus: true,
  });
}

export function useQueuePlan() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (lectureIds: string[]) => {
      const { data, error, response } = await api.POST("/api/v1/billing/queue-plan", {
        body: { lecture_ids: lectureIds },
      });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
    onSuccess: (waiting) => {
      queryClient.setQueryData(waitingQueryKey, waiting);
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["billing"] });
      void queryClient.invalidateQueries({ queryKey: ["lectures"] });
      void queryClient.invalidateQueries({ queryKey: ["courses"] });
    },
  });
}

export function planErrorOf(error: unknown) {
  if (error instanceof ApiError) {
    const detail = (error.body as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === "string") return detail;
    return "Не получилось запустить обработку. Попробуйте ещё раз";
  }
  return "Не удалось связаться с сервером. Проверьте интернет и попробуйте ещё раз";
}
