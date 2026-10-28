import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { components } from "../../api/schema";
import { ApiError } from "../../app/queryClient";

export type AdminAction = components["schemas"]["AdminAction"];
export type AuditEntry = components["schemas"]["AuditEntryOut"];
export type Admin = components["schemas"]["AdminOut"];

export const auditPageSize = 50;

const adminsQueryKey = ["admin", "admins"] as const;
const auditQueryKey = ["admin", "audit"] as const;

export type AuditFilters = {
  action: AdminAction | null;
  actorId: string | null;
  page: number;
};

export function errorMessage(error: unknown, fallback: string) {
  if (error instanceof ApiError) {
    const detail = (error.body as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

export function useAdmins() {
  return useQuery({
    queryKey: adminsQueryKey,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/admin/admins");
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });
}

export function useAudit({ action, actorId, page }: AuditFilters) {
  return useQuery({
    queryKey: [...auditQueryKey, action, actorId, page],
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/admin/audit", {
        params: {
          query: {
            action,
            actor_id: actorId,
            limit: auditPageSize,
            offset: (page - 1) * auditPageSize,
          },
        },
      });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });
}

function useRefreshAdminData() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: adminsQueryKey }),
      queryClient.invalidateQueries({ queryKey: auditQueryKey }),
    ]);
}

export function useGrantAdmin() {
  const refresh = useRefreshAdminData();
  return useMutation({
    mutationFn: async (identifier: string) => {
      const { data, error, response } = await api.POST("/api/v1/admin/admins", { body: { identifier } });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
    onSuccess: refresh,
  });
}

export function useRevokeAdmin() {
  const refresh = useRefreshAdminData();
  return useMutation({
    mutationFn: async (userId: string) => {
      const { error, response } = await api.DELETE("/api/v1/admin/admins/{user_id}", {
        params: { path: { user_id: userId } },
      });
      if (!response.ok) throw new ApiError(response.status, error);
    },
    onSuccess: refresh,
  });
}
