import { createContext, useContext } from "react";

/**
 * The store the owner is working on. The session lists the owner's store ids; the API does not
 * serve a store's name yet (reported as an API gap), so `name` stays null and screens say "Your
 * store" until it does.
 */
export interface StoreRef {
  storeId: string;
  name: string | null;
}

export const StoreContext = createContext<StoreRef | null>(null);

export function useStore(): StoreRef {
  const store = useContext(StoreContext);
  if (!store) throw new Error("useStore needs a signed-in session above it");
  return store;
}

export function storeLabel(store: StoreRef): string {
  return store.name ?? "Your store";
}

/** "Northwind Outdoor" → "NO": the store avatar's letters. */
export function initials(label: string): string {
  const letters = label
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word.charAt(0).toUpperCase());
  return letters.join("");
}
