import { useCallback } from "react";
import { useSearchParams } from "react-router";

const param = "quota";
const value = "plan";

export function useQuotaDialogParam() {
  const [searchParams, setSearchParams] = useSearchParams();
  const open = searchParams.get(param) === value;

  const setOpen = useCallback(
    (next: boolean) =>
      setSearchParams(
        (params) => {
          if (next) {
            params.delete("add");
            params.set(param, value);
          } else {
            params.delete(param);
          }
          return params;
        },
        { replace: true },
      ),
    [setSearchParams],
  );

  return { open, setOpen, adding: searchParams.has("add") };
}
