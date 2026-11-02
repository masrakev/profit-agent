import { useState } from "react";
import { createBrowserRouter, RouterProvider } from "react-router";

import { ApiProvider } from "@/api/ApiProvider";
import { routes } from "@/router";
import { ThemeProvider } from "@/theme/ThemeProvider";

export function App() {
  const [router] = useState(() => createBrowserRouter(routes()));
  return (
    <ApiProvider>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </ApiProvider>
  );
}
