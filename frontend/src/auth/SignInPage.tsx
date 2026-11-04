import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";

import { useDemo, useOpenDemo } from "./demo";
import {
  clearFragment,
  tokenFromFragment,
  useOpenSession,
  useRequestLink,
  useSession,
} from "./session";
import { ApiError } from "@/api/client";
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

/** Mailpit, the local inbox of `make up`: where a local demo server's emails arrive. */
const LOCAL_INBOX = "http://localhost:8025";

/**
 * Sign in by email link (ADR 0020). The page asks for a link, and exchanges the token of a link
 * that opened it (`/sign-in#token=…`), removing it from the address bar first. On a demo server
 * (the API says so), exploring its demo store comes first: one click, no email.
 */
export function SignInPage() {
  const session = useSession();
  const location = useLocation();
  const navigate = useNavigate();
  const next = destination(location.state);
  const [token, setToken] = useState(() => tokenFromFragment(window.location.hash));
  // A link opened in this same tab changes only the fragment: read it then too.
  useEffect(() => {
    const read = () => {
      const fresh = tokenFromFragment(window.location.hash);
      if (fresh) {
        exchanged.current = false;
        setToken(fresh);
      }
    };
    window.addEventListener("hashchange", read);
    return () => {
      window.removeEventListener("hashchange", read);
    };
  }, []);
  const exchange = useOpenSession();
  const exchanged = useRef(false);
  const server = useDemo().data;
  const demo = server?.available === true;

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
          <p className="text-small text-ink-muted">
            Every number proven. Nothing changes without you.
          </p>
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
            demo={demo}
            localInbox={server ? server.available && server.local_inbox : false}
            notice={exchange.isError ? sessionProblem(exchange.error) : null}
            onSignedIn={() => {
              void navigate(next, { replace: true });
            }}
          />
        )}
      </main>
    </div>
  );
}

interface LinkFormProps {
  /** A demo server: exploring its demo store comes first, the email form after it. */
  demo: boolean;
  /** Its emails stay in the local inbox (Mailpit): the page says where to read them. */
  localInbox: boolean;
  /** Why the owner is back on the form (a link that failed), shown above it. */
  notice: string | null;
  onSignedIn: () => void;
}

function LinkForm({ demo, localInbox, notice, onSignedIn }: LinkFormProps) {
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
        {localInbox && (
          <p className="text-small text-ink-muted">
            This is a demo server: its emails arrive in its local inbox,{" "}
            <a
              href={LOCAL_INBOX}
              target="_blank"
              rel="noreferrer"
              className="font-medium text-accent-ink underline-offset-4 hover:underline"
            >
              open it
            </a>
            . Only the demo store's owner has an account here.
          </p>
        )}
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
      {demo && <ExploreDemo onSignedIn={onSignedIn} />}
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
      <Button
        type="submit"
        block
        variant={demo ? "secondary" : "primary"}
        disabled={request.isPending}
        aria-busy={request.isPending}
      >
        {request.isPending ? "Sending…" : "Email me a sign-in link"}
      </Button>
      <SecurityNote />
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

/** A demo server's demo store, opened in one click as its owner, without an email. */
function ExploreDemo({ onSignedIn }: { onSignedIn: () => void }) {
  const open = useOpenDemo();
  return (
    <div className="flex flex-col gap-3 border-b border-line pb-5">
      <Button
        block
        disabled={open.isPending}
        aria-busy={open.isPending}
        onClick={() => {
          open.mutate(undefined, { onSuccess: onSignedIn });
        }}
      >
        {open.isPending ? "Opening the demo store…" : "Explore the demo store"}
      </Button>
      <p className="text-center text-label text-ink-muted">
        A sample outdoor store, with its data, its decisions and its goals. No email needed.
      </p>
      {open.isError && (
        <p role="alert" className="text-label leading-[1.45] text-danger-ink">
          The demo store could not be opened. Try again in a moment.
        </p>
      )}
    </div>
  );
}
