import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { outcomeOf, predicted, useFacts } from "./facts";
import { SOURCES, statusOf } from "./status";
import { unwrap, type Schemas } from "@/api/client";
import { useApi } from "@/api/context";
import { CompareRanges } from "@/charts/CompareRanges";
import { RangeBar } from "@/charts/RangeBar";
import { TrustMeter } from "@/charts/TrustMeter";
import { DecisionMessage } from "@/conversation/DecisionMessage";
import { useOpen } from "@/conversation/open";
import { RichText } from "@/conversation/RichText";
import { FactValue } from "@/facts/FactValue";
import { estimateOf } from "@/facts/facts";
import { VerifiedSeal } from "@/facts/VerifiedSeal";
import { formatDay, formatTime, localDay } from "@/format/dates";
import { useHere } from "@/shell/here";
import { useStore } from "@/stores/store";
import { AgentMark } from "@/ui/AgentMark";
import { Button } from "@/ui/Button";
import { cx } from "@/ui/cx";
import { Section } from "@/ui/Section";
import { Skeleton } from "@/ui/Skeleton";
import { StatusPill } from "@/ui/StatusPill";

type Decision = Schemas["DecisionView"];
type Entry = Schemas["JournalEntry"];

/** Why a decision exists, from its cause, in the owner's words. */
const CAUSES: Record<string, string> = {
  stockout_on_promoted: "Ads keep spending on a product that is out of stock.",
  cpa_drift: "The cost per purchase keeps rising.",
  cannibalization: "The ads may be buying sales that would happen anyway.",
  supplier_cost_increase: "The unit cost from the supplier went up.",
  refund_spike: "Refunds rose sharply.",
  mix_shift: "Sales moved towards lower-margin products.",
  fee_increase: "Fees per order went up.",
  tracking_break: "The ad platform's tracking looks broken.",
  budget_review: "My budget review found a change the twin expects to pay.",
  owner_change: "You asked for this change.",
};

const CHANNELS: Record<string, string> = {
  web: "in the app",
  api: "with an API token",
  email: "from the email link",
  whatsapp: "on WhatsApp",
};

const text = (v: unknown) => (typeof v === "string" ? v : null);

/**
 * One decision, read top to bottom like an email: the question, why, the options (the approval
 * card while it waits), what was decided, by whom and from where, what the platform reports, what
 * it earned against what was predicted, and what it is linked to.
 */
export function DecisionDetail({ decisionId }: { decisionId: string }) {
  const api = useApi();
  const open = useOpen();
  const { storeId, timezone } = useStore();
  const decision = useQuery({
    queryKey: ["decision", storeId, decisionId],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/stores/{store_id}/decisions/{decision_id}", {
          params: { path: { store_id: storeId, decision_id: decisionId } },
        }),
      ),
  });
  const d = decision.data;
  const titled = d?.options.find((o) => o.option_id === d.approved_option_id)?.label ?? d?.label;
  useHere(d && titled ? { kind: "decision", id: d.decision_id, label: titled } : null);
  if (decision.isPending) return <Skeleton rows={4} />;
  if (!d) {
    return <p className="text-body text-ink-muted">This decision could not be loaded.</p>;
  }
  const status = statusOf(d.status);
  const chosen = d.options.find((o) => o.option_id === d.approved_option_id);
  const waiting = d.status === "proposed";
  return (
    <section aria-label={chosen?.label ?? d.label} className="flex flex-col gap-10">
      <header className="flex flex-col gap-3">
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-label text-ink-muted">
          <AgentMark size="sm" state={waiting ? "waiting" : "idle"} />
          <span>{SOURCES[d.source] ?? d.source}</span>
          <time className="font-mono">{localDay(d.created_at, timezone).label}</time>
          {waiting && <span>Expires {formatDay(d.expires_at.slice(0, 10))}</span>}
        </p>
        <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
          <h2
            className={cx(
              "text-title font-semibold text-ink",
              d.status === "superseded" && "text-ink-muted line-through",
            )}
          >
            {chosen?.label ?? d.label}
          </h2>
          <span className="flex shrink-0 flex-wrap items-center gap-2">
            <StatusPill tone={status.tone}>{status.text}</StatusPill>
            <Button
              variant="secondary"
              className="h-8 px-3 text-label"
              onClick={() => {
                open.ask({ kind: "decision", id: d.decision_id, label: chosen?.label ?? d.label });
              }}
            >
              Ask about this decision
            </Button>
          </span>
        </div>
      </header>
      <Why decision={d} />
      {waiting ? (
        <Section level={3} title="What I propose">
          <div className="pt-5">
            <DecisionMessage decisionId={d.decision_id} />
          </div>
        </Section>
      ) : (
        <>
          <Options decision={d} />
          <Decided decision={d} />
          <Section level={3} title="What happened">
            <div className="pt-5">
              <DecisionMessage decisionId={d.decision_id} headless />
            </div>
          </Section>
          <Earned decision={d} />
        </>
      )}
      <Linked decision={d} />
    </section>
  );
}

function Why({ decision: d }: { decision: Decision }) {
  const open = useOpen();
  const facts = useFacts([predicted(d)]);
  const expected = facts.get(predicted(d) ?? -1);
  return (
    <Section level={3} title="Why">
      <div className="flex flex-col gap-4 pt-5">
        <p className="max-w-[65ch] text-body text-ink">
          {CAUSES[d.cause] ?? d.cause.replaceAll("_", " ")}
        </p>
        {expected && (
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-small text-ink">
            <span className="text-ink-muted">
              Expected over {String(d.horizon_days)} days, compared with doing nothing:
            </span>
            <FactValue fact={expected} title="Expected change in net profit" />
            <VerifiedSeal fact={expected} />
          </p>
        )}
        {d.incident_id && (
          <div>
            <Button
              variant="secondary"
              className="h-9 px-4 text-small"
              onClick={() => {
                if (d.incident_id) open.investigation(d.incident_id);
              }}
            >
              What I checked
            </Button>
          </div>
        )}
      </div>
    </Section>
  );
}

/** Once decided, the options as they were proposed, the chosen one marked. */
function Options({ decision: d }: { decision: Decision }) {
  const facts = useFacts([...d.options.map((o) => o.impact_fact_id), d.do_nothing.impact_fact_id]);
  const zero = facts.get(d.do_nothing.impact_fact_id ?? -1);
  return (
    <Section level={3} title="What I proposed">
      <ul className="flex flex-col">
        {d.options.map((o) => {
          const impact = facts.get(o.impact_fact_id ?? -1);
          const picked = o.option_id === d.approved_option_id;
          return (
            <li key={o.option_id} className="flex flex-col gap-3 border-b border-line py-4">
              <p className="flex items-baseline justify-between gap-3 text-body text-ink">
                <span className={cx(picked && "font-medium")}>{o.label}</span>
                {picked ? (
                  <span className="shrink-0 text-label text-accent-ink">Chosen</span>
                ) : (
                  o.option_id === d.recommended_option_id && (
                    <span className="shrink-0 text-label text-ink-muted">Recommended</span>
                  )
                )}
              </p>
              {impact &&
                (estimateOf(impact) ? (
                  <RangeBar fact={impact} title={o.label} />
                ) : (
                  <FactValue fact={impact} title={o.label} className="self-start text-small" />
                ))}
            </li>
          );
        })}
        <li className="flex items-baseline justify-between gap-3 border-b border-line py-4 text-body text-ink-muted">
          <span>{d.do_nothing.label}</span>
          {zero && <FactValue fact={zero} title={d.do_nothing.label} />}
        </li>
      </ul>
    </Section>
  );
}

/** Who answered, when and from where, as the journal records it. */
function Decided({ decision: d }: { decision: Decision }) {
  const entries = useDecisionJournal(d.decision_id);
  const { timezone } = useStore();
  const answers = (entries ?? []).filter((e) => e.kind === "approval");
  if (answers.length === 0) return null;
  return (
    <Section level={3} title="What was decided">
      <ul className="flex flex-col">
        {answers.map((e) => {
          const s = e.summary as Record<string, unknown>;
          const who = text(s["actor"])?.startsWith("owner:")
            ? "You"
            : (text(s["actor"]) ?? "Someone");
          const verdict = s["verdict"] === "approved" ? "approved it" : "said not now";
          const where = CHANNELS[text(s["channel"]) ?? ""] ?? "";
          return (
            <li
              key={e.id}
              className="flex flex-wrap items-baseline justify-between gap-3 border-b border-line py-4"
            >
              <span className="text-body text-ink">
                {who} {verdict} {where}.
              </span>
              <time className="font-mono text-label text-ink-muted">
                {localDay(e.at, timezone).label}, {formatTime(e.at, timezone)}
              </time>
            </li>
          );
        })}
      </ul>
    </Section>
  );
}

/** What it earned: the measured effect against the prediction, with the backend's verdict. */
function Earned({ decision: d }: { decision: Decision }) {
  const api = useApi();
  const { storeId } = useStore();
  const outcome = outcomeOf(d);
  const facts = useFacts([outcome?.predicted_fact_id ?? predicted(d), outcome?.effect_fact_id]);
  const expected = facts.get(outcome?.predicted_fact_id ?? predicted(d) ?? -1);
  const measured = facts.get(outcome?.effect_fact_id ?? -1);
  const trust = useQuery({
    queryKey: ["trust", storeId],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/stores/{store_id}/trust", { params: { path: { store_id: storeId } } }),
      ),
  });
  const option = d.options.find((o) => o.option_id === (d.approved_option_id ?? ""));
  const kind = text(option?.actions[0]?.["kind"]);
  const entry = trust.data?.find((t) => t.action_type === kind);
  if (!["executed", "measured", "failed"].includes(d.status)) return null;
  return (
    <Section level={3} title="What it earned">
      <div className="flex flex-col gap-4 pt-5">
        {measured ? (
          <>
            <CompareRanges
              rows={[
                ...(expected ? [{ label: "Predicted", fact: expected }] : []),
                { label: "Measured", fact: measured },
              ]}
            />
            <p className="text-label text-ink-muted">
              Both over the same week, from the day it took effect.
            </p>
            {outcome?.verdict_text && <p className="text-body text-ink">{outcome.verdict_text}</p>}
          </>
        ) : (
          <p className="text-body text-ink-muted">
            {outcome?.status === "abstained"
              ? "I could not measure it reliably yet: I will try again with more days."
              : "I measure what it earned once a full week has passed since it took effect."}
          </p>
        )}
        {entry?.progress && (
          <p className="flex flex-wrap items-center gap-2.5 text-label text-ink-muted">
            <TrustMeter confirmations={entry.confirmations} threshold={entry.threshold} />
            {entry.progress}
          </p>
        )}
      </div>
    </Section>
  );
}

/** What the decision is tied to: its goal's step, the decision that replaced it. */
function Linked({ decision: d }: { decision: Decision }) {
  const step = useGoalStep(d.goal_step);
  const replacement = d.superseded_by;
  if (!step && !replacement) return null;
  return (
    <Section level={3} title="Linked to">
      <ul className="flex flex-col">
        {step && (
          <li className="flex flex-col gap-1 border-b border-line py-4">
            <span className="text-label text-ink-muted">
              Step {step.position} of your goal&apos;s plan
            </span>
            <Link
              to={`/goals/${step.goal_id}`}
              className="rounded-md text-body text-ink underline decoration-line underline-offset-4 hover:decoration-ink-muted"
            >
              {step.summary ? (
                <RichText text={step.summary} facts={step.facts} names={step.names} />
              ) : (
                "Open the goal"
              )}
            </Link>
          </li>
        )}
        {replacement && (
          <li className="flex flex-col gap-1 border-b border-line py-4">
            <span className="text-label text-ink-muted">Replaced by</span>
            <Link
              to={`/decisions/${replacement}`}
              className="rounded-md text-body text-ink underline decoration-line underline-offset-4 hover:decoration-ink-muted"
            >
              The newer decision on the same campaign
            </Link>
          </li>
        )}
      </ul>
    </Section>
  );
}

/** The journal's entries about one decision (its answers and actions). */
function useDecisionJournal(decisionId: string): Entry[] | undefined {
  const api = useApi();
  const { storeId } = useStore();
  const journal = useQuery({
    queryKey: ["journal", storeId, "decision", decisionId],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/stores/{store_id}/journal", {
          params: { path: { store_id: storeId }, query: { limit: 200 } },
        }),
      ),
  });
  return journal.data?.items.filter(
    (e) => (e.summary as { decision_id?: unknown }).decision_id === decisionId,
  );
}

/** The goal step this decision carries out (the API names it): its words, from its plan. */
function useGoalStep(link: Decision["goal_step"]) {
  const api = useApi();
  const { storeId } = useStore();
  const plans = useQuery({
    queryKey: ["goal-plans", storeId, link?.goal_id, "of-decision"],
    enabled: link != null,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/stores/{store_id}/goals/{goal_id}/plans", {
          params: { path: { store_id: storeId, goal_id: link?.goal_id ?? "" } },
        }),
      ),
  });
  if (!link) return null;
  const plan = plans.data?.find((p) => p.plan_id === link.plan_id);
  const step = plan?.steps.find((s) => s.step_id === link.step_id);
  return {
    ...link,
    summary: step?.summary ?? null,
    facts: plan?.facts ?? {},
    names: plan?.names ?? {},
  };
}
