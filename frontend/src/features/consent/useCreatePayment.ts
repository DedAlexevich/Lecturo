import { useMutation } from "@tanstack/react-query";
import { api } from "../../api/client";
import { ApiError } from "../../app/queryClient";

type PaymentRequest = {
  productCode: string;
  acceptOffer: boolean;
};

export function useCreatePayment() {
  return useMutation({
    mutationFn: async ({ productCode, acceptOffer }: PaymentRequest) => {
      if (!acceptOffer) throw new Error("Для оплаты нужно принять оферту");
      const { data, error, response } = await api.POST("/api/v1/billing/payments", {
        body: {
          product_code: productCode,
          accept_offer: true,
          return_url: `${window.location.origin}/account`,
        },
      });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
    onSuccess: (payment) => {
      if (payment.confirmation_url) window.location.assign(payment.confirmation_url);
    },
  });
}
