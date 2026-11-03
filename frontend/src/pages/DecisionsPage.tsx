import { useQueries, useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { unwrap, type Schemas } from "@/api/client";
import { useApi } from "@/api/context";
import { CompareRanges } from "@/charts/CompareRanges";
import { useOpenInChat } from "@/conversation/open";
import { SOURCES, statusOf } from "@/decisions/status";
import { FactValue } from "@/facts/FactValue";
import { factKey, type Fact } from "@/facts/facts";
import { VerifiedSeal } from "@/facts/VerifiedSeal";
import { localDay } from "@/format/dates";
import { useStore } from "@/stores/store";
import { Button } from "@/ui/Button";
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
 * Every decision the agent proposed, by where it stands: what it expected (a range), and once
 * measured, what happened, on the same axis. Above them, earned autonomy: how far the agent may
 * act alone for each kind of action, and a promotion only when the trust ledger proposes one.
 */
export function DecisionsPage() {
  const api = useApi();
  const { storeId } = useStore();
  const path = { store_id: storeId };

  const decisions = useQuery({
    queryKey: ["decisions", storeId],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/stores/{store_id}/decisions", {
          params: { path, query: { limit: 200 } },
        }),
      ),
  });
  const trust = useQuery({
    queryKey: ["trust", storeId],
    queryFn: () => unwrap(api.GET("/api/v1/stores/{store_id}/trust", { params: { path } })),
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
            params: { path: { ...path, fact_id: factId } },
          }),
        ),
    })),
  });
  const facts = new Map<number, Fact>(
    factQueries.flatMap((q) => (q.data ? [[q.data.fact.fact_id, q.data.fact] as const] : [])),
  );

  return (
    <section aria-labelledby="decisions-title" className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <h1 id="decisions-title" className="text-title font-semibold text-ink">
          Decisions
        </h1>
        <p className="text-body text-ink-muted">
          What I proposed, what you answered, and what came of it.
        </p>
      </header>
      {trust.data && trust.data.length > 0 && <Autonomy entries={trust.data} />}
      {decisions.isPending && (
        <p className="h-40 animate-pulse rounded-card bg-subtle" aria-busy="true" />
      )}
      {decisions.isError && (
        <p className="text-body text-ink-muted">The decisions could not be loaded.</p>
      )}
      {decisions.data && items.length === 0 && (
        <p className="text-body text-ink-muted">No decision yet.</p>
      )}
      {GROUPS.map((group) => {
        const mine = items.filter((d) => group.statuses.includes(d.status));
        if (mine.length === 0) return null;
        return (
          <section key={group.title} aria-label={group.title} className="flex flex-col gap-3">
            <h2 className="text-small font-semibold text-ink">{group.title}</h2>
            {mine.map((d) => (
              <DecisionRow
                key={d.decision_id}
                decision={d}
                expected={facts.get(outcomeOf(d)?.predicted_fact_id ?? predicted(d) ?? -1)}
                measured={facts.get(outcomeOf(d)?.effect_fact_id ?? -1)}
              />
            ))}
          </section>
        );
      })}
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
  expected,
  measured,
}: {
  decision: Decision;
  expected: Fact | undefined;
  measured: Fact | undefined;
}) {
  const open = useOpenInChat();
  const { timezone } = useStore();
  const chosen = decision.options.find((o) => o.option_id === decision.approved_option_id);
  const status = statusOf(decision.status);
  const sealed = measured ?? expected;
  return (
    <article
      aria-label={chosen?.label ?? decision.label}
      className="flex flex-col gap-4 rounded-card border border-line bg-surface p-5"
    >
      <header className="flex items-start gap-3">
        <div className="flex flex-1 flex-col gap-1">
          <h3 className="text-body font-semibold text-ink">{chosen?.label ?? decision.label}</h3>
          <p className="text-label text-ink-muted">
            {SOURCES[decision.source] ?? decision.source} ·{" "}
            {localDay(decision.created_at, timezone).label}
          </p>
        </div>
        {sealed && <VerifiedSeal fact={sealed} />}
        <StatusPill tone={status.tone}>{status.text}</StatusPill>
      </header>
      {measured ? (
        <div className="flex flex-col gap-2">
          <CompareRanges
            rows={[
              ...(expected ? [{ label: "Predicted", fact: expected }] : []),
              { label: "Measured", fact: measured },
            ]}
          />
          {outcomeOf(decision)?.verdict_text && (
            <p className="text-small text-ink">{outcomeOf(decision)?.verdict_text}</p>
          )}
        </div>
      ) : (
        expected && (
          <p className="text-small text-ink">
            <span className="text-ink-muted">
              {decision.status === "proposed"
                ? "Expected, compared with doing nothing: "
                : "Expected: "}
            </span>
            <FactValue fact={expected} title="Expected change in net profit" />
          </p>
        )
      )}
      {decision.status === "superseded" && (
        <p className="text-small text-ink-muted">Replaced by a newer decision.</p>
      )}
      <div className="flex flex-wrap gap-2.5">
        <Button
          variant={decision.status === "proposed" ? "primary" : "secondary"}
          className="h-9 px-4 text-small"
          onClick={() => {
            open.decision(decision.decision_id);
          }}
        >
          {decision.status === "proposed" ? "Review" : "Open in the conversation"}
        </Button>
      </div>
    </article>
  );
}

/** How far the agent may act alone, per kind of action; a promotion only when it is proposed. */
function Autonomy({ entries }: { entries: Trust[] }) {
  return (
    <section
      aria-labelledby="autonomy-title"
      className="flex flex-col gap-4 rounded-card border border-line bg-surface p-6 shadow-float"
    >
      <div className="flex flex-col gap-1">
        <h2 id="autonomy-title" className="text-small font-semibold text-ink">
          Earned autonomy
        </h2>
        <p className="text-label text-ink-muted">
          I ask to act alone only after enough of my predictions held, measured.
        </p>
      </div>
      <ul className="flex flex-col divide-y divide-line">
        {entries.map((entry) => (
          <li
            key={entry.action_type}
            className="flex flex-wrap items-center justify-between gap-3 py-3 first:pt-0 last:pb-0"
          >
            <div className="flex flex-col">
              <span className="text-small font-semibold text-ink">
                {ACTIONS[entry.action_type] ?? entry.action_type}
              </span>
              <span className="text-label text-ink-muted">
                {LEVELS[entry.level] ?? "Its level is not known"}
              </span>
              {entry.progress && (
                <span className="text-label text-ink-muted">{entry.progress}</span>
              )}
            </div>
            {entry.proposal && (
              <Link
                to="/settings"
                className="inline-flex h-9 items-center rounded-full bg-accent-fill px-4 text-small font-semibold text-on-accent"
              >
                Always allow
              </Link>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
