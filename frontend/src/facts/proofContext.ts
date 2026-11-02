import { createContext, useContext } from "react";

import type { Fact } from "./facts";

export interface ProofControls {
  /** Opens the proof sheet on a fact. `title` names it in its context ("Gain from pausing"). */
  open: (fact: Fact, title?: string) => void;
}

export const ProofContext = createContext<ProofControls | null>(null);

export function useProof(): ProofControls {
  const controls = useContext(ProofContext);
  if (!controls) throw new Error("useProof needs a <ProofProvider> above it");
  return controls;
}
