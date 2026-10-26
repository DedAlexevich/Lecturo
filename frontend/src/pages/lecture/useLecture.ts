import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { ApiError } from "../../app/queryClient";

const POLL_INTERVAL_MS = 5000;
const pendingStatuses = new Set(["queued", "waiting_quota", "processing"]);

export function lectureQueryKey(id: string) {
  return ["lectures", id] as const;
}

export function useLecture(id: string) {
  return useQuery({
    queryKey: lectureQueryKey(id),
    refetchInterval: (query) =>
      query.state.data && pendingStatuses.has(query.state.data.status) ? POLL_INTERVAL_MS : false,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/lectures/{lecture_id}", {
        params: { path: { lecture_id: id } },
      });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });
}
