import { createContext, useContext } from "react";
import type { Evidence, Page } from "./types";
export type Target = { page: Page; id?: string };
export const Navigation = createContext<{
  go: (target: Target) => void;
  showEvidence: (evidence: Evidence) => void;
}>({ go: () => {}, showEvidence: () => {} });
export const useNavigation = () => useContext(Navigation);
