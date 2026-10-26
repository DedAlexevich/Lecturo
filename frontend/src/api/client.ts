import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "./schema";

const TOKEN_KEY = "lecturo.token";

export const tokenStorage = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (token: string) => localStorage.setItem(TOKEN_KEY, token),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

const auth: Middleware = {
  onRequest({ request }) {
    const token = tokenStorage.get();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
};

export const api = createClient<paths>({ baseUrl: "" });
api.use(auth);
