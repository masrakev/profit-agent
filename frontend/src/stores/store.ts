import { createContext, useContext } from "react";

import { unwrap, type Api, type Schemas } from "@/api/client";

export type StoreInfo = Schemas["StoreOut"];

/**
 * The store the owner is working on: the session lists the owner's store ids, the API names
 * each one. `name` is null only while the store could not be read; screens then say "Your store".
 */
export interface StoreRef {
  storeId: string;
  name: string | null;
  /** A generated store (the demo): the header says so. */
  synthetic: boolean;
  /** The store's time zone (IANA), for times of day. */
  timezone: string;
}

export const storeKey = (storeId: string) => ["store", storeId] as const;

export function fetchStore(api: Api, storeId: string): Promise<StoreInfo> {
  return unwrap(api.GET("/api/v1/stores/{store_id}", { params: { path: { store_id: storeId } } }));
}

export const StoreContext = createContext<StoreRef | null>(null);

export function useStore(): StoreRef {
  const store = useContext(StoreContext);
  if (!store) throw new Error("useStore needs a signed-in session above it");
  return store;
}

export function storeLabel(store: Pick<StoreRef, "name">): string {
  return store.name ?? "Your store";
}

/** The header's line: the store's name, and "Demo store" for a generated one. */
export function storeLine(store: StoreRef): string {
  return store.synthetic ? `${storeLabel(store)} · Demo store` : storeLabel(store);
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
