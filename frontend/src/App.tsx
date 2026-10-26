import { useEffect, useState } from "react";
import { api } from "./api/client";

export function App() {
  const [status, setStatus] = useState("проверяем сервер");

  useEffect(() => {
    api.GET("/api/v1/health").then(({ data }) => setStatus(data?.status === "ok" ? "сервер на связи" : "сервер недоступен"));
  }, []);

  return (
    <main>
      <h1>Lecturo</h1>
      <p>{status}</p>
    </main>
  );
}
