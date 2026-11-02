import "@/styles/index.css";

import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { createQueryClient } from "@/api/queryClient";
import { App } from "@/App";
import { initTheme } from "@/theme/theme";

const root = document.getElementById("root");
if (!root) throw new Error("the page has no #root element");

initTheme(); // before the first paint, so a dark system never flashes light

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={createQueryClient()}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
