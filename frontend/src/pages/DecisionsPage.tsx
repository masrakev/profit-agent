import { useQueries, useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";

import { unwrap, type Schemas } from "@/api/client";
import { useApi } from "@/api/context";
import { CompareRanges } from "@/charts/CompareRanges";
import { TrustMeter } from "@/charts/TrustMeter";
import { DecisionMessage } from "@/conversation/DecisionMessage";
import { SOURCES, statusOf } from "@/decisions/status";
import { useDecisions } from "@/decisions/useDecisions";
import { FactValue } from "@/facts/FactValue";
import { factKey, type Fact } from "@/facts/facts";
import { VerifiedSeal } from "@/facts/VerifiedSeal";
import { localDay } from "@/format/dates";
import { useStore } from "@/stores/store";
import { Button } from "@/ui/Button";
import { cx } from "@/ui/cx";
import { EmptyState } from "@/ui/EmptyState";
import { Icon } from "@/ui/Icon";
import { Section } from "@/ui/Section";
import { Skeleton } from "@/ui/Skeleton";
import { StatusPill } from "@/ui/StatusPill";

type Decision = Schemas["DecisionView"];
type Trust = Schemas["TrustEntry"];
type Outcome = Decision["outcomes"][number];

/** The decisions by where they stand, the owner's first. */
const GROUPS: { title: string; statuses: string[] }[] = [
  { title: "Waiting for you", statuses: ["proposed"] },
  { title: "In progress", statuses: ["approved", "executing"] },
  { title: "Done", statuses: ["executed", "measured", "failed"] },
  { title: "Closed", statuses: ["rejected", "expired", "superseded"] },
];

const ACTIONS: Record<string, string> = {
  pause_campaign: "Pausing a campaign",
  resume_campaign: "Resuming a campaign",
  change_budget: "Changing a daily budget",
};

/** SPEC section 7: what the agent may do alone, by level. */
const LEVELS: Record<number, string> = {
  1: "I only watch",
  2: "I ask you first, every time",
  3: "I act alone within your caps",
  4: "I manage it within its scope",
};

/**
 * Every decision the agent proposed, by where it stands, as rows: what it expected (a range) and,
 * once measured, what happened, on the same axis, with the backend's verdict. A row opens in
 * place: for a decision waiting for the owner, that is the approval moment; for the others, what
 * the platform reports. Above them, earned autonomy. Everything that asks the owner to decide
 * lives here, not in the conversation.
 */
export function DecisionsPage() {
  const api = useApi();
  const { storeId } = useStore();
  const [params] = useSearchParams();
  const asked = params.get("open");
  const decisions = useDecisions();
  const trust = useQuery({
    queryKey: ["trust", storeId],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/stores/{store_id}/trust", { params: { path: { store_id: storeId } } }),
      ),
  });

  const items = decisions.data?.items ?? [];
  const ids = items
    .flatMap((d) => {
      const o = outcomeOf(d);
      return [o?.predicted_fact_id ?? predicted(d), o?.effect_fact_id];
    })
    .flatMap((id) => (id == null ? [] : [id]));
  const factQueries = useQueries({
    queries: [...new Set(ids)].map((factId) => ({
      queryKey: factKey(storeId, factId),
      staleTime: Infinity,
      queryFn: () =>
        unwrap(
          api.GET("/api/v1/stores/{store_id}/facts/{fact_id}", {
            params: { path: { store_id: storeId, fact_id: factId } },
          }),
        ),
    })),
  });
  const facts = new Map<number, Fact>(
    factQueries.flatMap((q) => (q.data ? [[q.data.fact.fact_id, q.data.fact] as const] : [])),
  );

  return (
    <section aria-labelledby="decisions-title" className="flex flex-col gap-12">
      <header className="flex flex-col gap-2">
        <h1 id="decisions-title" className="text-title font-semibold text-ink">
          Decisions
        </h1>
        <p className="text-body text-ink-muted">
          What I proposed, what you answered, and what came of it.
        </p>
      </header>
      {decisions.isPending && <Skeleton rows={4} />}
      {decisions.isError && (
        <p className="text-body text-ink-muted">The decisions could not be loaded.</p>
      )}
      {decisions.data && items.length === 0 && (
        <EmptyState title="No decision yet.">
          When I find something worth changing, I simulate it first and ask you here, with what it
          should earn and what could go wrong.
        </EmptyState>
      )}
      {GROUPS.map((group) => {
        const mine = items.filter((d) => group.statuses.includes(d.status));
        if (mine.length === 0) return null;
        return (
          <Section key={group.title} title={group.title}>
            <ul className="flex flex-col" data-stagger>
              {mine.map((d) => (
                <DecisionRow
                  key={d.decision_id}
                  decision={d}
                  opened={asked === d.decision_id}
                  expected={facts.get(outcomeOf(d)?.predicted_fact_id ?? predicted(d) ?? -1)}
                  measured={facts.get(outcomeOf(d)?.effect_fact_id ?? -1)}
                />
              ))}
            </ul>
          </Section>
        );
      })}
      {trust.data && trust.data.length > 0 && <Autonomy entries={trust.data} />}
    </section>
  );
}

/** Its latest measured outcome, else its latest one (an abstention says why). */
function outcomeOf(d: Decision): Outcome | undefined {
  return d.outcomes.findLast((o) => o.status === "measured") ?? d.outcomes.at(-1);
}

/** The impact the decision expects: its chosen option's, or the recommended one's. */
function predicted(d: Decision): number | null {
  const id = d.approved_option_id ?? d.recommended_option_id;
  return d.options.find((o) => o.option_id === id)?.impact_fact_id ?? null;
}

function DecisionRow({
  decision,
  opened,
  expected,
  measured,
}: {
  decision: Decision;
  opened: boolean;
  expected: Fact | undefined;
  measured: Fact | undefined;
}) {
  const { timezone } = useStore();
  const [open, setOpen] = useState(opened);
  const row = useRef<HTMLLIElement>(null);
  const detailsId = useId();
  const chosen = decision.options.find((o) => o.option_id === decision.approved_option_id);
  const status = statusOf(decision.status);
  const sealed = measured ?? expected;
  const waiting = decision.status === "proposed";
  const verdict = outcomeOf(decision)?.verdict_text;

  useEffect(() => {
    if (!opened) return;
    setOpen(true);
    row.current?.scrollIntoView({ block: "start", behavior: "smooth" });
  }, [opened]);

  return (
    <li ref={row} className="scroll-mt-6 border-b border-line">
      <article aria-label={chosen?.label ?? decision.label} className="flex flex-col gap-3 py-5">
        <header className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between sm:gap-3">
          <div className="flex min-w-0 flex-col gap-1">
            <h3
              className={cx(
                "text-body font-medium text-ink",
                decision.status === "superseded" && "text-ink-muted line-through",
              )}
            >
              {chosen?.label ?? decision.label}
            </h3>
            <p className="text-label text-ink-muted">
              {SOURCES[decision.source] ?? decision.source} ·{" "}
              <time className="font-mono">{localDay(decision.created_at, timezone).label}</time>
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-3">
            {sealed && <VerifiedSeal fact={sealed} />}
            <StatusPill tone={status.tone}>{status.text}</StatusPill>
          </div>
        </header>
        {measured ? (
          <div className="flex flex-col gap-2.5">
            <CompareRanges
              rows={[
                ...(expected ? [{ label: "Predicted", fact: expected }] : []),
                { label: "Measured", fact: measured },
              ]}
            />
            {verdict && <p className="text-small text-ink">{verdict}</p>}
          </div>
        ) : (
          expected && (
            <p className="text-small text-ink">
              <span className="text-ink-muted">
                {waiting ? "Expected, compared with doing nothing: " : "Expected: "}
              </span>
              <FactValue fact={expected} title="Expected change in net profit" />
            </p>
          )
        )}
        {decision.status === "superseded" && (
          <p className="text-small text-ink-muted">Replaced by a newer decision.</p>
        )}
        <div className="flex">
          <Button
            variant={waiting && !open ? "primary" : "ghost"}
            aria-expanded={open}
            aria-controls={detailsId}
            className={cx("h-9 text-small", waiting && !open ? "px-4" : "-ml-3 px-3")}
            onClick={() => {
              setOpen((was) => !was);
            }}
          >
            {waiting ? (open ? "Hide" : "Review") : open ? "Hide details" : "Details"}
            {!waiting && (
              <Icon
                name="chevron-up"
                size={16}
                className={cx("transition-transform duration-200", !open && "rotate-180")}
              />
            )}
          </Button>
        </div>
      </article>
      <div id={detailsId} hidden={!open} className="pb-6">
        {open && <DecisionMessage decisionId={decision.decision_id} />}
      </div>
    </li>
  );
}

/** How far the agent may act alone, per kind of action; a promotion only when it is proposed. */
function Autonomy({ entries }: { entries: Trust[] }) {
  return (
    <Section
      title="Earned autonomy"
      aside={
        <span className="hidden text-label text-ink-muted sm:inline">
          I ask to act alone only after enough of my predictions held.
        </span>
      }
    >
      <ul className="flex flex-col">
        {entries.map((entry) => (
          <li
            key={entry.action_type}
            className="flex flex-wrap items-center justify-between gap-3 border-b border-line py-4"
          >
            <div className="flex min-w-0 flex-col gap-1">
              <span className="text-body font-medium text-ink">
                {ACTIONS[entry.action_type] ?? entry.action_type}
              </span>
              <span className="text-small text-ink-muted">
                {LEVELS[entry.level] ?? "Its level is not known"}
              </span>
              {entry.progress && (
                <span className="flex flex-wrap items-center gap-2.5 text-label text-ink-muted">
                  <TrustMeter confirmations={entry.confirmations} threshold={entry.threshold} />
                  {entry.progress}
                </span>
              )}
            </div>
            {entry.proposal && (
              <Link
                to="/settings"
                className="inline-flex h-9 items-center rounded-full bg-accent-fill px-4 text-small font-medium text-on-accent hover:opacity-90"
              >
                Always allow
              </Link>
            )}
          </li>
        ))}
      </ul>
    </Section>
  );
}
