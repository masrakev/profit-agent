import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { createQueryClient } from "@/api/queryClient";
import { App } from "@/App";

const root = document.getElementById("root");
if (!root) throw new Error("the page has no #root element");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={createQueryClient()}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
