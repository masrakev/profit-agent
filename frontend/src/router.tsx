import type { RouteObject } from "react-router";

import { RequireSession } from "@/auth/RequireSession";
import { SignInPage } from "@/auth/SignInPage";
import { ChatPage } from "@/pages/ChatPage";
import { NotFoundPage, PendingPage } from "@/pages/placeholders";
import { AppShell, type RouteHandle } from "@/shell/AppShell";

const conversation: RouteHandle = { composer: true };

/** Every page. `dev` adds the component catalogue (`/style-guide`), absent from production. */
export function routes(dev: boolean = import.meta.env.DEV): RouteObject[] {
  const signedIn: RouteObject[] = [
    { index: true, element: <ChatPage />, handle: conversation },
    { path: "today", element: <PendingPage title="Today" /> },
    { path: "decisions", element: <PendingPage title="Decisions" /> },
    { path: "goals", element: <PendingPage title="Goals" /> },
    { path: "journal", element: <PendingPage title="Journal" /> },
    { path: "settings", element: <PendingPage title="Settings" /> },
  ];
  const gated: RouteObject[] = [{ element: <AppShell />, children: signedIn }];
  // `import.meta.env.DEV` first: a production build drops this branch and the page with it.
  if (import.meta.env.DEV && dev) {
    gated.push({
      path: "style-guide",
      lazy: async () => ({ Component: (await import("@/dev/StyleGuidePage")).StyleGuidePage }),
    });
  }
  return [
    { path: "/sign-in", element: <SignInPage /> },
    { element: <RequireSession />, children: gated },
    { path: "*", element: <NotFoundPage /> },
  ];
}
