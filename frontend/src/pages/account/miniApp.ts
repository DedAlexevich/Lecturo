import { getWebApp } from "../../telegram/sdk";

export function getMiniAppInitData() {
  return getWebApp()?.initData ?? "";
}
