import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../../api/client";
import type { components } from "../../../api/schema";
import { ApiError } from "../../../app/queryClient";

export type UserBrief = components["schemas"]["UserBriefOut"];
export type UserCard = components["schemas"]["UserCardOut"];
export type Stats = components["schemas"]["StatsOut"];
export type StatsDay = components["schemas"]["StatsDayOut"];
export type LectureStatus = components["schemas"]["LectureStatus"];

const usersQueryKey = ["admin", "users"] as const;
const auditQueryKey = ["admin", "audit"] as const;

export function userQueryKey(userId: string) {
  return [...usersQueryKey, "card", userId] as const;
}

export function useUserSearch(query: string) {
  return useQuery({
    queryKey: [...usersQueryKey, "search", query],
    enabled: query.length >= 2,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/admin/users", { params: { query: { q: query } } });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });
}

export function useUserCard(userId: string) {
  return useQuery({
    queryKey: userQueryKey(userId),
    staleTime: 5 * 60_000,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/admin/users/{user_id}", {
        params: { path: { user_id: userId } },
      });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });
}

export type UserAction =
  | { kind: "hours"; hours: number; reason: string }
  | { kind: "subscription"; days: number; reason: string }
  | { kind: "block"; reason: string }
  | { kind: "unblock"; reason: string };

async function runAction(userId: string, action: UserAction) {
  const path = { params: { path: { user_id: userId } } };
  const result =
    action.kind === "hours"
      ? await api.POST("/api/v1/admin/users/{user_id}/hours", {
          ...path,
          body: { hours: action.hours, reason: action.reason },
        })
      : action.kind === "subscription"
        ? await api.POST("/api/v1/admin/users/{user_id}/subscription", {
            ...path,
            body: { days: action.days, reason: action.reason },
          })
        : action.kind === "block"
          ? await api.POST("/api/v1/admin/users/{user_id}/block", { ...path, body: { reason: action.reason } })
          : await api.POST("/api/v1/admin/users/{user_id}/unblock", { ...path, body: { reason: action.reason } });
  if (result.data === undefined) throw new ApiError(result.response.status, result.error);
  return result.data;
}

export function useUserAction(userId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (action: UserAction) => runAction(userId, action),
    onSuccess: (card) => {
      queryClient.setQueryData(userQueryKey(userId), card);
      return Promise.all([
        queryClient.invalidateQueries({ queryKey: [...usersQueryKey, "search"] }),
        queryClient.invalidateQueries({ queryKey: auditQueryKey }),
      ]);
    },
  });
}

export function useStats(dateFrom: string, dateTo: string) {
  return useQuery({
    queryKey: ["admin", "stats", dateFrom, dateTo],
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/admin/stats", {
        params: { query: { date_from: dateFrom, date_to: dateTo } },
      });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });
}
