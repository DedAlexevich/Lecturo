import { useSyncExternalStore } from "react";
import { api, tokenStorage } from "../api/client";
import { queryClient } from "./queryClient";

const listeners = new Set<() => void>();

function notify() {
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

export function signIn(token: string) {
  tokenStorage.set(token);
  queryClient.clear();
  notify();
}

export function signOut() {
  tokenStorage.clear();
  queryClient.clear();
  notify();
}

export function useToken() {
  return useSyncExternalStore(subscribe, tokenStorage.get);
}

api.use({
  onResponse({ request, response }) {
    if (response.status === 401 && request.headers.has("Authorization")) signOut();
    return response;
  },
});
