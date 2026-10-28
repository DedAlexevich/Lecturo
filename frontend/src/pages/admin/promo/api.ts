import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../../api/client";
import type { components } from "../../../api/schema";
import { ApiError } from "../../../app/queryClient";

export type PromoCode = components["schemas"]["PromoCodeOut"];
export type PromoCreate = components["schemas"]["PromoCreateIn"];
export type PromoKind = components["schemas"]["PromoKind"];
export type PromoRedemption = components["schemas"]["PromoRedemptionOut"];

const promoQueryKey = ["admin", "promo"] as const;
const auditQueryKey = ["admin", "audit"] as const;

export function usePromoCodes() {
  return useQuery({
    queryKey: promoQueryKey,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/admin/promo-codes");
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });
}

export function usePromoRedemptions(promoId: string) {
  return useQuery({
    queryKey: [...promoQueryKey, "redemptions", promoId],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/admin/promo-codes/{promo_id}/redemptions", {
        params: { path: { promo_id: promoId } },
      });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });
}

function useRefreshPromo() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: promoQueryKey }),
      queryClient.invalidateQueries({ queryKey: auditQueryKey }),
    ]);
}

export function useCreatePromo() {
  const refresh = useRefreshPromo();
  return useMutation({
    mutationFn: async (body: PromoCreate) => {
      const { data, error, response } = await api.POST("/api/v1/admin/promo-codes", { body });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
    onSuccess: refresh,
  });
}

export function useDisablePromo() {
  const refresh = useRefreshPromo();
  return useMutation({
    mutationFn: async (promoId: string) => {
      const { data, error, response } = await api.POST("/api/v1/admin/promo-codes/{promo_id}/disable", {
        params: { path: { promo_id: promoId } },
      });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
    onSuccess: refresh,
  });
}
