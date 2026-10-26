import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { components } from "../../api/schema";
import { ApiError } from "../../app/queryClient";

export type Quota = components["schemas"]["QuotaOut"];
export type Product = components["schemas"]["ProductOut"];
export type Payment = components["schemas"]["PaymentOut"];

export const quotaQueryKey = ["billing", "quota"] as const;
export const productsQueryKey = ["billing", "products"] as const;
export const paymentsQueryKey = ["billing", "payments"] as const;

export function errorMessage(error: unknown, fallback: string) {
  if (error instanceof ApiError) {
    const detail = (error.body as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

export function useQuota() {
  return useQuery({
    queryKey: quotaQueryKey,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/billing/quota");
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });
}

export function useProducts() {
  return useQuery({
    queryKey: productsQueryKey,
    staleTime: 5 * 60_000,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/billing/products");
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });
}

export function usePayments(refetchInterval?: number | false) {
  return useQuery({
    queryKey: paymentsQueryKey,
    refetchInterval,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/v1/billing/payments");
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
  });
}

type CreatePayment = {
  productCode: string;
  idempotenceKey: string;
};

export const paymentReturnParam = "payment";

const pendingPaymentPrefix = "lecturo.payment.";

function rememberPayment(returnKey: string, paymentId: string) {
  try {
    sessionStorage.setItem(pendingPaymentPrefix + returnKey, paymentId);
  } catch {
    return;
  }
}

export function rememberedPayment(returnKey: string) {
  try {
    return sessionStorage.getItem(pendingPaymentPrefix + returnKey);
  } catch {
    return null;
  }
}

export function useCreatePayment() {
  return useMutation({
    mutationFn: async ({ productCode, idempotenceKey }: CreatePayment) => {
      const returnUrl = new URL("/account", window.location.origin);
      returnUrl.searchParams.set(paymentReturnParam, idempotenceKey);
      const { data, error, response } = await api.POST("/api/v1/billing/payments", {
        params: { header: { "Idempotence-Key": idempotenceKey } },
        body: { product_code: productCode, accept_offer: true, return_url: returnUrl.toString() },
      });
      if (data === undefined) throw new ApiError(response.status, error);
      rememberPayment(idempotenceKey, data.id);
      return data;
    },
  });
}
