import { createContext } from "react";

// Undefined allows these controls to retain inline feedback outside a workbench.
export const NodeWorkbenchFeedbackContext = createContext<HTMLDivElement | null | undefined>(undefined);
