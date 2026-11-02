import { useCallback, useMemo, useRef, useState, type ReactNode } from "react";

import type { Fact } from "./facts";
import { ProofContext, type ProofControls } from "./proofContext";
import { ProofSheet } from "./ProofSheet";

interface Opened {
  fact: Fact;
  title?: string;
}

/**
 * Every number on screen opens its proof here. Opening a parent fact from inside the sheet stacks
 * it, so "Back" returns to the number the owner started from; closing gives focus back to it.
 */
export function ProofProvider({ storeId, children }: { storeId: string; children: ReactNode }) {
  const [stack, setStack] = useState<Opened[]>([]);
  const opener = useRef<HTMLElement | null>(null);

  const open = useCallback((fact: Fact, title?: string) => {
    const active = document.activeElement;
    // A number opened from inside the sheet stacks on it; focus still returns to the first opener.
    if (active instanceof HTMLElement && !active.closest("[data-proof-sheet]")) {
      opener.current = active;
    }
    setStack((current) => [...current, title === undefined ? { fact } : { fact, title }]);
  }, []);

  const close = useCallback(() => {
    setStack([]);
    opener.current?.focus();
    opener.current = null;
  }, []);

  const back = useCallback(() => {
    setStack((current) => current.slice(0, -1));
  }, []);

  const controls = useMemo<ProofControls>(() => ({ open }), [open]);
  const shown = stack.at(-1);

  return (
    <ProofContext.Provider value={controls}>
      {children}
      {shown && (
        <ProofSheet
          key={`${String(stack.length)}:${String(shown.fact.fact_id)}`}
          storeId={storeId}
          fact={shown.fact}
          title={shown.title}
          onClose={close}
          onBack={stack.length > 1 ? back : undefined}
        />
      )}
    </ProofContext.Provider>
  );
}
