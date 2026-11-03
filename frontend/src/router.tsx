import { Navigate, type RouteObject } from "react-router";

import { ApprovalPage } from "@/approval/ApprovalPage";
import { RequireSession } from "@/auth/RequireSession";
import { SignInPage } from "@/auth/SignInPage";
import { ChatPage } from "@/pages/ChatPage";
import { DecisionsPage } from "@/pages/DecisionsPage";
import { GoalsPage } from "@/pages/GoalsPage";
import { HomePage } from "@/pages/HomePage";
import { JournalPage } from "@/pages/JournalPage";
import { NotFoundPage } from "@/pages/placeholders";
import { SettingsPage } from "@/pages/SettingsPage";
import { AppShell, type RouteHandle } from "@/shell/AppShell";

const conversation: RouteHandle = { composer: true };

/** Every page. `dev` adds the component catalogue (`/style-guide`), absent from production. */
export function routes(dev: boolean = import.meta.env.DEV): RouteObject[] {
  const signedIn: RouteObject[] = [
    { index: true, element: <HomePage />, handle: conversation },
    { path: "chat", element: <ChatPage />, handle: conversation },
    // Today became Home: an old link still lands on the day.
    { path: "today", element: <Navigate to="/" replace /> },
    { path: "decisions", element: <DecisionsPage /> },
    { path: "goals", element: <GoalsPage /> },
    { path: "journal", element: <JournalPage /> },
    { path: "settings", element: <SettingsPage /> },
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
    { path: "/approve", element: <ApprovalPage /> },
    { element: <RequireSession />, children: gated },
    { path: "*", element: <NotFoundPage /> },
  ];
}
