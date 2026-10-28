import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { reloadOnPreloadError } from "./app/preloadReload";
import "@fontsource-variable/inter/wght.css";
import { registerServiceWorker } from "./pwa/register";
import { loadTelegramSdk } from "./telegram/loadSdk";
import "./styles/tokens.css";
import "./styles/base.css";

reloadOnPreloadError();
registerServiceWorker();

void loadTelegramSdk()
  .then(() => import("./App"))
  .then(({ App }) => {
    createRoot(document.getElementById("root")!).render(
      <StrictMode>
        <App />
      </StrictMode>,
    );
  });
