import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router";

import { ApiError, unwrap, type Schemas } from "@/api/client";
import { useApi } from "@/api/context";
import { approvalToken } from "./token";
import { clearFragment } from "@/auth/session";
import { BRAND } from "@/brand";
import { BrandMark } from "@/ui/BrandMark";
import { Button } from "@/ui/Button";
import { Icon } from "@/ui/Icon";

type LinkResult = Schemas["LinkResult"];

interface Problem {
  title: string;
  text: string;
}

function problemOf(code: string | undefined): Problem {
  switch (code) {
    case "expired_link":
      return {
        title: "This link has expired",
        text: "Approval links work for 24 hours. The decision may still be waiting for you in the app.",
      };
    case "used_link":
      return {
        title: "This link was already used",
        text: "Each approval link works once. The decision and what happened since are in the app.",
      };
    case "superseded":
      return {
        title: "Replaced by a newer decision",
        text: "A newer decision about the same campaign or product, on more recent data, took its place. Nothing changed from this one.",
      };
    case "already_decided":
      return {
        title: "This decision was already decided",
        text: "It was answered from another channel. Nothing more changes from this link.",
      };
    case "expired":
      return {
        title: "This decision has expired",
        text: "Nobody answered it in time, so nothing changed.",
      };
    default:
      return {
        title: "This link is not valid",
        text: "Open the latest email, or the app, to see what is waiting for you.",
      };
  }
}

/** Why a link to a decision that is no longer waiting cannot decide it (its preview says so). */
function closedCode(status: string): string | null {
  if (status === "proposed") return null;
  return status === "superseded" || status === "expired" ? status : "already_decided";
}

/**
 * The page an email's Approve or Decline link opens. Opening it only shows what it would decide
 * (mail scanners open links): the owner confirms with a button, which decides. Beyond the
 * spending caps, the link only points to the app. Expired, used and replaced links say so, and so
 * does a link to a decision no longer waiting (replaced, expired or decided elsewhere).
 */
export function ApprovalPage() {
  // Another email link opened in this tab changes only the fragment: the page reads it afresh.
  const [opened, setOpened] = useState(0);
  useEffect(() => {
    const follow = () => {
      if (window.location.hash) setOpened((count) => count + 1);
    };
    window.addEventListener("hashchange", follow);
    return () => {
      window.removeEventListener("hashchange", follow);
    };
  }, []);
  return <ApprovalLink key={opened} />;
}

function ApprovalLink() {
  const api = useApi();
  const [token] = useState(() => approvalToken(window.location.hash));
  useEffect(() => {
    if (token) clearFragment(); // the token is the approval: it leaves the address bar
  }, [token]);
  const path = { params: { path: { token: token ?? "" } } };

  const preview = useQuery({
    queryKey: ["approval-link", token],
    enabled: token !== null,
    retry: false,
    staleTime: Infinity,
    gcTime: 0, // opened again, a link is read again (it may have been used since)
    queryFn: () => unwrap(api.GET("/api/v1/approval-links/{token}", path)),
  });
  const confirm = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/approval-links/{token}", path)),
  });

  const error = token === null ? new ApiError(403, undefined) : (confirm.error ?? preview.error);
  const closed = preview.data && !confirm.data ? closedCode(preview.data.decision.status) : null;
  return (
    <div className="flex min-h-dvh flex-col items-center gap-[100px] bg-canvas px-6 pt-14 pb-12 sm:px-16">
      <BrandMark named />
      <main className="flex w-full max-w-[460px] flex-col gap-6">
        {error ? (
          <Message {...problemOf(error instanceof ApiError ? error.code : undefined)} />
        ) : confirm.data ? (
          <Done result={confirm.data} />
        ) : closed ? (
          <Message {...problemOf(closed)} />
        ) : preview.data ? (
          <Confirm
            result={preview.data}
            pending={confirm.isPending}
            onConfirm={() => {
              confirm.mutate();
            }}
          />
        ) : (
          <p role="status" className="text-center text-body text-ink-muted">
            Opening your approval link…
          </p>
        )}
      </main>
      <footer className="mt-auto text-label text-ink-muted">{BRAND.name}</footer>
    </div>
  );
}

function optionLabel(result: LinkResult): string | null {
  return result.decision.options.find((o) => o.option_id === result.option_id)?.label ?? null;
}

function Confirm({
  result,
  pending,
  onConfirm,
}: {
  result: LinkResult;
  pending: boolean;
  onConfirm: () => void;
}) {
  const approving = result.verdict === "approved";
  const option = optionLabel(result);
  return (
    <>
      <div className="flex flex-col gap-3 text-center">
        <p className="text-small text-ink-muted">From your email</p>
        <h1 className="text-title font-semibold text-ink">
          {approving ? "Approve this?" : "Decline this?"}
        </h1>
      </div>
      <section className="flex flex-col gap-5 rounded-card border border-line bg-surface p-7">
        <h2 className="text-card font-semibold text-ink">{result.decision.label}</h2>
        {approving && option && option !== result.decision.label.replace(/\?$/, "") && (
          <p className="text-body text-ink">{option}</p>
        )}
        {result.confirmation_required ? (
          <p role="note" className="rounded-box bg-subtle p-4 text-small text-ink">
            This goes beyond your spending caps, so it is approved in the app, where you see its
            numbers.
          </p>
        ) : (
          <p className="text-small text-ink-muted">
            {approving
              ? "Approving carries it out within your spending caps; you can undo it."
              : "Declining changes nothing."}
          </p>
        )}
        <div className="flex flex-wrap gap-2.5">
          {!result.confirmation_required && (
            <Button
              variant={approving ? "primary" : "danger"}
              onClick={onConfirm}
              disabled={pending}
              aria-busy={pending}
            >
              {pending ? "Sending…" : approving ? "Approve" : "Decline"}
            </Button>
          )}
          <OpenApp primary={result.confirmation_required} />
        </div>
        <p className="flex items-start gap-2 text-label leading-[1.45] text-ink-muted">
          <Icon name="lock-keyhole" size={16} />
          The link works once, for this decision only.
        </p>
      </section>
    </>
  );
}

function Done({ result }: { result: LinkResult }) {
  const approved = result.verdict === "approved";
  return (
    <Message
      title={approved ? "Approved" : "Declined"}
      text={
        approved
          ? `${result.decision.label.replace(/\?$/, "")}: it is being carried out within your spending caps. You can follow it, and undo it, in the app.`
          : "Nothing changes. The decision stays in your journal."
      }
      done
    />
  );
}

function Message({ title, text, done = false }: Problem & { done?: boolean }) {
  return (
    <section className="flex flex-col items-center gap-4 rounded-card border border-line bg-surface p-7 text-center">
      <span className="inline-flex size-10 items-center justify-center rounded-full bg-accent-soft text-accent-ink">
        <Icon name={done ? "circle-check" : "x"} />
      </span>
      <h1 className="text-card font-semibold text-ink">{title}</h1>
      <p className="text-body text-ink-muted">{text}</p>
      <OpenApp primary={false} />
    </section>
  );
}

function OpenApp({ primary }: { primary: boolean }) {
  return (
    <Link
      to="/"
      className={
        primary
          ? "inline-flex h-[42px] items-center justify-center rounded-full bg-accent-fill px-5 text-body font-semibold text-on-accent"
          : "inline-flex h-[42px] items-center justify-center rounded-full bg-subtle px-5 text-body font-semibold text-ink hover:bg-line"
      }
    >
      Open the app
    </Link>
  );
}
