import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { useToast } from "../../ui/Toast";
import { paymentReturnParam, paymentsQueryKey, quotaQueryKey, usePayments } from "./billing";

const pollInterval = 3000;
const pollLimit = 2 * 60_000;

export function usePaymentReturn() {
  const [params, setParams] = useSearchParams();
  const returned = params.has(paymentReturnParam);
  const queryClient = useQueryClient();
  const toast = useToast();
  const [startedAt] = useState(() => Date.now());
  const handled = useRef(false);
  const { data: payments, dataUpdatedAt, isError } = usePayments(returned ? pollInterval : false);

  useEffect(() => {
    if (!returned || handled.current || (!payments && !isError)) return;
    const latest = payments?.[0];
    const finish = (message: string, tone: "success" | "info" | "error") => {
      handled.current = true;
      toast.show(message, tone);
      queryClient.invalidateQueries({ queryKey: quotaQueryKey });
      queryClient.invalidateQueries({ queryKey: paymentsQueryKey });
      setParams(
        (current) => {
          current.delete(paymentReturnParam);
          return current;
        },
        { replace: true },
      );
    };
    if (isError) finish("Не удалось проверить оплату. Обновите страницу чуть позже.", "error");
    else if (latest?.status === "succeeded") finish("Оплата прошла, лимит обновлён.", "success");
    else if (latest?.status === "canceled") finish("Платёж отменён, деньги не списаны.", "info");
    else if (!latest || Date.now() - startedAt > pollLimit)
      finish("Платёж ещё обрабатывается. Статус обновится в истории платежей.", "info");
  }, [returned, payments, dataUpdatedAt, isError, startedAt, toast, queryClient, setParams]);

  return returned && !handled.current;
}
