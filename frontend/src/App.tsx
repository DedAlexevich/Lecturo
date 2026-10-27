import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router";
import { queryClient } from "./app/queryClient";
import { router } from "./app/router";
import { UpdatePrompt } from "./pwa/UpdatePrompt";
import { ToastProvider } from "./ui/Toast";

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <RouterProvider router={router} />
        <UpdatePrompt />
      </ToastProvider>
    </QueryClientProvider>
  );
}
