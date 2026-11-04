import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";

import { useApi } from "@/api/context";
import { SESSION_KEY, useSession } from "@/auth/session";
import { BrandMark } from "@/ui/BrandMark";

/**
 * Development builds only: `/demo` opens the demo store (`make demo-seed`) on Home, signing in as
 * its owner when needed, so a demo starts on the product rather than on the sign-in page.
 */
export function DemoEntry() {
  const api = useApi();
  const queries = useQueryClient();
  const session = useSession();
  const navigate = useNavigate();
  const started = useRef(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    if (session.isPending || started.current) return;
    started.current = true;
    if (session.data) {
      void navigate("/", { replace: true });
      return;
    }
    void (async () => {
      try {
        const { demoSignIn } = await import("@/auth/demoSignIn");
        queries.setQueryData(SESSION_KEY, await demoSignIn(api));
        void navigate("/", { replace: true });
      } catch (error) {
        setProblem(error instanceof Error ? error.message : "The demo store could not be opened.");
      }
    })();
  }, [api, navigate, queries, session.data, session.isPending]);

  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-6 bg-canvas px-6">
      <BrandMark named />
      <p
        role="status"
        className={problem ? "text-small text-danger-ink" : "text-small text-ink-muted"}
      >
        {problem ?? "Opening the demo store…"}
      </p>
    </div>
  );
}
