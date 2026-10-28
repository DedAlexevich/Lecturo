import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { reloadOnPreloadError } from "./app/preloadReload";
import "@fontsource-variable/inter/wght.css";
import { registerServiceWorker } from "./pwa/register";
import "./styles/tokens.css";
import "./styles/base.css";

reloadOnPreloadError();
registerServiceWorker();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
