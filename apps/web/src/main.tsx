import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

const HealthProvider = lazy(() => import("./app/HealthProvider").then((module) => ({ default: module.HealthProvider })));

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Suspense fallback={null}>
      <HealthProvider>
        <App />
      </HealthProvider>
    </Suspense>
  </StrictMode>,
);
