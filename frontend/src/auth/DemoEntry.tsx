import { useEffect, useRef } from "react";
import { Link, useNavigate } from "react-router";

import { useOpenDemo } from "./demo";
import { ApiError } from "@/api/client";
import { useTheme } from "@/theme/context";
import { BrandMark } from "@/ui/BrandMark";

/**
 * `/demo`: on a demo server (`make demo-up`, or a hosted demo), opens its demo store on Home as its
 * owner, in the default (light) theme, without an email, however many times it is opened.
 * Anywhere else it says there is no demo here.
 */
export function DemoEntry() {
  const open = useOpenDemo();
  const navigate = useNavigate();
  const { setPreference } = useTheme();
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    setPreference("light");
    open.mutate(undefined, {
      onSuccess: () => {
        void navigate("/", { replace: true });
      },
    });
  }, [open, navigate, setPreference]);

  const absent = open.error instanceof ApiError && open.error.status === 404;
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-6 bg-canvas px-6 text-center">
      <BrandMark named />
      {open.isError ? (
        <div className="flex max-w-[52ch] flex-col items-center gap-3">
          <p role="status" className="text-body text-ink">
            {absent
              ? "This server has no demo store."
              : "The demo store could not be opened. Try again in a moment."}
          </p>
          <Link to="/sign-in" className="text-small font-medium text-accent-ink hover:underline">
            Sign in to your store
          </Link>
        </div>
      ) : (
        <p role="status" className="text-small text-ink-muted">
          Opening the demo store…
        </p>
      )}
    </div>
  );
}
