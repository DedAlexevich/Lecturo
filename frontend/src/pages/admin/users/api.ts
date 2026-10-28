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
const adminsQueryKey = ["admin", "admins"] as const;

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
    refetchOnWindowFocus: false,
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
  | { kind: "admin" }
  | { kind: "hours"; hours: number; reason: string }
  | { kind: "subscription"; days: number; reason: string }
  | { kind: "block"; reason: string }
  | { kind: "unblock"; reason: string };

function sendAction(userId: string, action: UserAction) {
  const path = { path: { user_id: userId } };
  switch (action.kind) {
    case "admin":
      return api.POST("/api/v1/admin/users/{user_id}/admin", { params: path });
    case "hours":
      return api.POST("/api/v1/admin/users/{user_id}/hours", {
        params: path,
        body: { hours: action.hours, reason: action.reason },
      });
    case "subscription":
      return api.POST("/api/v1/admin/users/{user_id}/subscription", {
        params: path,
        body: { days: action.days, reason: action.reason },
      });
    case "block":
      return api.POST("/api/v1/admin/users/{user_id}/block", { params: path, body: { reason: action.reason } });
    case "unblock":
      return api.POST("/api/v1/admin/users/{user_id}/unblock", { params: path, body: { reason: action.reason } });
  }
}

async function runAction(userId: string, action: UserAction) {
  const result = await sendAction(userId, action);
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
        queryClient.invalidateQueries({ queryKey: adminsQueryKey }),
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
