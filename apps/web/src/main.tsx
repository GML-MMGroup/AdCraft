import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { HealthProvider } from "./app/HealthProvider";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <HealthProvider>
      <App />
    </HealthProvider>
  </StrictMode>,
);
