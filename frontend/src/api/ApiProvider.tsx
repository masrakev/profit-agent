import type { ReactNode } from "react";

import { api as defaultApi, type Api } from "./client";
import { ApiContext } from "./context";

/** Provides the API client to hooks (tests pass one built on a fake `fetch`). */
export function ApiProvider({ api = defaultApi, children }: { api?: Api; children: ReactNode }) {
  return <ApiContext.Provider value={api}>{children}</ApiContext.Provider>;
}
