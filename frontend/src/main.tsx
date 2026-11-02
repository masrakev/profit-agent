import "@/styles/index.css";

import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { createQueryClient } from "@/api/queryClient";
import { App } from "@/App";
import { SESSION_KEY } from "@/auth/session";
import { initTheme } from "@/theme/theme";

const root = document.getElementById("root");
if (!root) throw new Error("the page has no #root element");

initTheme(); // before the first paint, so a dark system never flashes light

const queries = createQueryClient({
  // A session that expired mid-visit: forget it, and the gate sends the owner to sign in.
  onUnauthenticated: (client) => {
    client.setQueryData(SESSION_KEY, null);
  },
});

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queries}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
