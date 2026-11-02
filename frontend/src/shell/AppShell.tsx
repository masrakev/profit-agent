import { Outlet, useMatches } from "react-router";

import { Composer } from "./Composer";
import { NavRail } from "./NavRail";
import { TopBar } from "./TopBar";

/** A route asks for the composer dock with `handle: { composer: true }` (the conversation). */
export interface RouteHandle {
  composer?: boolean;
}

function wantsComposer(handle: unknown): boolean {
  return typeof handle === "object" && handle !== null && (handle as RouteHandle).composer === true;
}

/** The signed-in frame: the rail, the workspace header, the page, and the composer dock. */
export function AppShell() {
  const composer = useMatches().some((match) => wantsComposer(match.handle));
  return (
    <div className="min-h-dvh bg-canvas text-ink">
      <a
        href="#main"
        className="sr-only z-50 rounded-full bg-surface px-4 py-2 text-small text-ink focus:not-sr-only focus:fixed focus:top-3 focus:left-24"
      >
        Skip to content
      </a>
      <NavRail />
      <div className="flex min-h-dvh flex-col gap-7 pt-6 pr-10 pb-[120px] pl-[128px]">
        <TopBar />
        <main id="main" tabIndex={-1} className="mx-auto flex w-full max-w-[760px] flex-col gap-6">
          <Outlet />
        </main>
      </div>
      {composer && (
        <div className="pointer-events-none fixed inset-x-0 bottom-0 z-20 pr-10 pb-6 pl-[128px]">
          <div className="pointer-events-auto mx-auto w-full max-w-[760px]">
            <Composer />
          </div>
        </div>
      )}
    </div>
  );
}
