import { createContext, useContext, useEffect } from "react";

import type { Topic } from "@/conversation/context";

/** Sets what the page on screen is about (the shell keeps it for the Ask palette). */
export const HereContext = createContext<(topic: Topic | null) => void>(() => undefined);

/** Declares the decision or the goal a page shows, while it shows it. */
export function useHere(topic: Topic | null) {
  const set = useContext(HereContext);
  const kind = topic?.kind;
  const id = topic?.id;
  const label = topic?.label;
  useEffect(() => {
    set(kind && id && label ? { kind, id, label } : null);
    return () => {
      set(null);
    };
  }, [set, kind, id, label]);
}
