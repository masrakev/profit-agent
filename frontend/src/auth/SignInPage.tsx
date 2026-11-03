import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";

import {
  SESSION_KEY,
  clearFragment,
  tokenFromFragment,
  useOpenSession,
  useRequestLink,
  useSession,
} from "./session";
import { ApiError } from "@/api/client";
import { useApi } from "@/api/context";
import { BRAND } from "@/brand";
import { BrandMark } from "@/ui/BrandMark";
import { Button } from "@/ui/Button";
import { Icon } from "@/ui/Icon";

/** Where to go once signed in: the page the owner was sent away from, or the conversation. */
function destination(state: unknown): string {
  const from = (state as { from?: unknown } | null)?.from;
  return typeof from === "string" && from.startsWith("/") && !from.startsWith("//") ? from : "/";
}

function linkProblem(error: unknown): string {
  if (error instanceof ApiError && error.status === 429) {
    return "Too many sign-in requests. Wait a minute, then try again.";
  }
  if (error instanceof ApiError && error.status === 422) return "Enter a valid email address.";
  return "The link could not be sent. Check your connection and try again.";
}

function sessionProblem(error: unknown): string {
  if (error instanceof ApiError && error.isClientError) {
    return "This sign-in link has expired or was already used. Ask for a new one below.";
  }
  return "Signing in failed. Check your connection, then open the link again.";
}

/**
 * Sign in by email link (ADR 0020). The page asks for a link, and exchanges the token of a link
 * that opened it (`/sign-in#token=…`), removing it from the address bar first. Development builds
 * add "Use the demo store", which signs in as the demo owner through Mailpit.
 */
export function SignInPage() {
  const session = useSession();
  const location = useLocation();
  const navigate = useNavigate();
  const next = destination(location.state);
  const [token] = useState(() => tokenFromFragment(window.location.hash));
  const exchange = useOpenSession();
  const exchanged = useRef(false);

  useEffect(() => {
    if (!token || exchanged.current) return;
    exchanged.current = true;
    clearFragment();
    exchange.mutate(token, {
      onSuccess: () => {
        void navigate(next, { replace: true });
      },
    });
  }, [token, exchange, navigate, next]);

  if (session.data && !token) return <Navigate to={next} replace />;

  return (
    <div className="flex min-h-dvh flex-col items-center gap-[100px] bg-canvas px-6 pt-14 pb-12 sm:px-16">
      <BrandMark named />
      <main className="flex w-full max-w-[460px] flex-col gap-6">
        <div className="flex flex-col gap-3 text-center">
          <p className="text-small text-ink-muted">Your profit, a little clearer.</p>
          <h1 className="text-title font-semibold text-ink">Sign in to your store</h1>
          <p className="text-body text-ink-muted">
            No password to remember. We’ll send you a secure link.
          </p>
        </div>
        {exchange.isPending ? (
          <p
            role="status"
            className="rounded-card border border-line bg-surface p-7 text-center text-body text-ink"
          >
            Signing you in…
          </p>
        ) : (
          <LinkForm
            notice={exchange.isError ? sessionProblem(exchange.error) : null}
            onSignedIn={() => {
              void navigate(next, { replace: true });
            }}
          />
        )}
      </main>
      <footer className="mt-auto text-label text-ink-muted">{BRAND.name}</footer>
    </div>
  );
}

interface LinkFormProps {
  /** Why the owner is back on the form (a link that failed), shown above it. */
  notice: string | null;
  onSignedIn: () => void;
}

function LinkForm({ notice, onSignedIn }: LinkFormProps) {
  const request = useRequestLink();
  const [email, setEmail] = useState("");
  const [sentTo, setSentTo] = useState<string | null>(null);
  const emailId = useId();
  const problemId = useId();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const address = email.trim();
    request.mutate(address, {
      onSuccess: () => {
        setSentTo(address);
      },
    });
  };

  if (sentTo) {
    return (
      <section
        role="status"
        className="flex flex-col gap-5 rounded-card border border-line bg-surface p-7"
      >
        <h2 className="text-heading font-semibold text-ink">Check your email</h2>
        <p className="text-body text-ink">
          If <span className="font-semibold">{sentTo}</span> has an account, a sign-in link is on
          its way. Open it on this device.
        </p>
        <SecurityNote />
        <Button
          variant="ghost"
          className="self-start px-0 hover:bg-transparent hover:underline"
          onClick={() => {
            setSentTo(null);
            setEmail("");
            request.reset();
          }}
        >
          Use a different address
        </Button>
      </section>
    );
  }

  const problem = request.isError ? linkProblem(request.error) : null;
  return (
    <form
      onSubmit={submit}
      className="flex flex-col gap-5 rounded-card border border-line bg-surface p-7"
    >
      {notice && (
        <p role="alert" className="rounded-box bg-subtle p-4 text-small text-ink">
          {notice}
        </p>
      )}
      <div className="flex flex-col gap-2">
        <label htmlFor={emailId} className="text-small font-semibold text-ink">
          Email
        </label>
        <input
          id={emailId}
          type="email"
          required
          autoComplete="email"
          inputMode="email"
          spellCheck={false}
          maxLength={320}
          value={email}
          onChange={(event) => {
            setEmail(event.target.value);
          }}
          aria-invalid={problem ? true : undefined}
          aria-describedby={problem ? problemId : undefined}
          className="h-[52px] w-full rounded-box border border-line bg-surface px-4 text-body text-ink outline-none placeholder:text-ink-muted focus:border-accent-mark"
        />
        {problem && (
          <p id={problemId} role="alert" className="text-label leading-[1.45] text-danger-ink">
            {problem}
          </p>
        )}
      </div>
      <Button type="submit" block disabled={request.isPending} aria-busy={request.isPending}>
        {request.isPending ? "Sending…" : "Email me a sign-in link"}
      </Button>
      <SecurityNote />
      {import.meta.env.DEV && <DemoSignIn onSignedIn={onSignedIn} />}
    </form>
  );
}

/** As the API documents it: a link is single use and valid 15 minutes. */
function SecurityNote() {
  return (
    <p className="flex items-start gap-2 text-label leading-[1.45] text-ink-muted">
      <Icon name="lock-keyhole" size={16} />
      The link expires in 15 minutes and can only be used once.
    </p>
  );
}

/** Development builds only: one click signs in as the demo store's owner. */
function DemoSignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const api = useApi();
  const queries = useQueryClient();
  const [state, setState] = useState<{ busy: boolean; problem: string | null }>({
    busy: false,
    problem: null,
  });

  const signIn = async () => {
    setState({ busy: true, problem: null });
    try {
      const { demoSignIn } = await import("./demoSignIn");
      queries.setQueryData(SESSION_KEY, await demoSignIn(api));
      onSignedIn();
    } catch (error) {
      setState({
        busy: false,
        problem: error instanceof Error ? error.message : "The demo sign-in failed.",
      });
    }
  };

  return (
    <div className="flex flex-col gap-2 border-t border-line pt-5">
      <Button
        variant="secondary"
        block
        disabled={state.busy}
        aria-busy={state.busy}
        onClick={() => {
          void signIn();
        }}
      >
        {state.busy ? "Opening the demo store…" : "Use the demo store"}
      </Button>
      <p className="text-center text-caption text-ink-muted">Development build only</p>
      {state.problem && (
        <p role="alert" className="text-label leading-[1.45] text-danger-ink">
          {state.problem}
        </p>
      )}
    </div>
  );
}
