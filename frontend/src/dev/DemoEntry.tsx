import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";

import { ApiError, unwrap } from "@/api/client";
import { useApi } from "@/api/context";
import { SESSION_KEY } from "@/auth/session";
import { useTheme } from "@/theme/context";
import { BrandMark } from "@/ui/BrandMark";

const NOT_RUNNING =
  "The demo is not running on this server. Start it with `make demo-up`, then reload.";

/**
 * Development builds only: `/demo` opens the demo store on Home, in the default (light) theme.
 * The demo API (`make demo-up`) opens its owner's session directly, without a sign-in email, so a
 * demo starts on the product, however many times it is opened.
 */
export function DemoEntry() {
  const api = useApi();
  const queries = useQueryClient();
  const navigate = useNavigate();
  const { setPreference } = useTheme();
  const started = useRef(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    setPreference("light");
    void (async () => {
      try {
        const session = await unwrap(api.POST("/api/v1/auth/demo-session"));
        queries.setQueryData(SESSION_KEY, session);
        void navigate("/", { replace: true });
      } catch (error) {
        setProblem(
          error instanceof ApiError && error.status === 404
            ? NOT_RUNNING
            : "The demo could not be opened. Try again in a moment.",
        );
      }
    })();
  }, [api, navigate, queries, setPreference]);

  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-6 bg-canvas px-6">
      <BrandMark named />
      <p
        role="status"
        className={
          problem ? "max-w-[52ch] text-center text-small text-ink" : "text-small text-ink-muted"
        }
      >
        {problem ?? "Opening the demo store…"}
      </p>
    </div>
  );
}
