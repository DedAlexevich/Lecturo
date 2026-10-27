import { useSyncExternalStore } from "react";
import { api, tokenStorage } from "../api/client";
import { queryClient } from "./queryClient";

const listeners = new Set<() => void>();
let signedOutByUser = false;

export function wasSignedOutByUser() {
  return signedOutByUser;
}

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
  signedOutByUser = false;
  tokenStorage.set(token);
  queryClient.clear();
  notify();
}

function resetSession() {
  tokenStorage.clear();
  queryClient.clear();
  notify();
}

export function signOut() {
  signedOutByUser = true;
  resetSession();
}

export function useToken() {
  return useSyncExternalStore(subscribe, tokenStorage.get);
}

const localAuthErrors = ["/api/v1/me/identities/telegram", "/api/v1/me/identities/vk", "/api/v1/me/identities/yandex", "/api/v1/me/delete"];

api.use({
  onResponse({ request, response }) {
    const token = tokenStorage.get();
    if (response.status !== 401 || token === null) return response;
    if (localAuthErrors.includes(new URL(request.url).pathname)) return response;
    if (request.headers.get("Authorization") === `Bearer ${token}`) resetSession();
    return response;
  },
});
