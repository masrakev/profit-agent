import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { unwrap, type Schemas } from "@/api/client";
import { useApi } from "@/api/context";
import { CompareRanges } from "@/charts/CompareRanges";
import { FanChart, type FanWeek } from "@/charts/FanChart";
import { VerdictBand } from "@/charts/VerdictBand";
import { RangeBar } from "@/charts/RangeBar";
import { statusOf } from "@/decisions/status";
import { useDecisions } from "@/decisions/useDecisions";
import { useOpen } from "@/conversation/open";
import { plainText } from "@/conversation/plain";
import { RichText, type Facts, type Names } from "@/conversation/RichText";
import { FactValue } from "@/facts/FactValue";
import type { Fact } from "@/facts/facts";
import { formatDay, formatLastDay } from "@/format/dates";
import { useGoalAsk } from "@/goals/ask";
import { Composer } from "@/shell/Composer";
import { useHere } from "@/shell/here";
import { useStore } from "@/stores/store";
import { Button } from "@/ui/Button";
import { cx } from "@/ui/cx";
import { EmptyState } from "@/ui/EmptyState";
import { Skeleton } from "@/ui/Skeleton";
import { StatusPill, type Tone } from "@/ui/StatusPill";

type Goal = Schemas["GoalOut"];
type Feasibility = Schemas["FeasibilityOut"];
type Plan = Schemas["PlanOut"];
type Step = Plan["steps"][number];
type Progress = Schemas["ProgressOut"];

interface Milestone {
  day: number;
  date: string;
  fact_id: number;
}
interface Experiment {
  lever: string;
  summary: string;
  experiment: { cap?: string; success?: string; duration_days?: number };
}
interface Checkpoint {
  day: number;
  date: string;
  fact_id: number;
}
/** What the plan's payload carries that the page shows (the API's own fields). */
interface PlanPayload {
  milestones?: Milestone[];
  experiments?: Experiment[];
  assumptions?: string[];
  target_fact_id?: number;
  outcome_fact_id?: number;
  profit_change_fact_id?: number;
  probability_with_fact_id?: number;
  probability_without_fact_id?: number;
}

const GOAL_STATUS: Record<string, { tone: Tone; text: string }> = {
  draft: { tone: "warning", text: "Waiting for your confirmation" },
  confirmed: { tone: "info", text: "Confirmed" },
  planned: { tone: "info", text: "Following its plan" },
  achieved: { tone: "good", text: "Reached" },
  missed: { tone: "neutral", text: "Not reached" },
  cancelled: { tone: "neutral", text: "Cancelled" },
};

/** Which goal leads the page when none was picked: the one being followed first. */
const LEAD = ["planned", "confirmed", "draft"];

const VERDICTS: Record<string, string> = {
  likely: "Likely",
  possible: "Possible",
  stretch: "A stretch",
  unlikely: "Unlikely",
};

const STEP_STATUS: Record<string, { tone: Tone; text: string }> = {
  planned: { tone: "neutral", text: "Planned" },
  proposed: { tone: "warning", text: "Waiting for you" },
  done: { tone: "good", text: "Done" },
  skipped: { tone: "neutral", text: "Skipped" },
  superseded: { tone: "neutral", text: "Replaced" },
};

const PROGRESS_STATUS: Record<string, { tone: Tone; text: string }> = {
  ahead: { tone: "good", text: "Ahead of the plan" },
  on_track: { tone: "good", text: "On track" },
  behind: { tone: "critical", text: "Behind the plan" },
  waiting_for_approval: { tone: "warning", text: "Waiting for your approval" },
};

const LEVERS: Record<string, string> = {
  price_test: "Price test",
  refund_reduction: "Fewer refunds",
};

const words = (map: Record<string, { tone: Tone; text: string }>, key: string) =>
  map[key] ?? { tone: "neutral" as const, text: key.replaceAll("_", " ") };

/** The verdict in words: one when the band is one, else the band it lies in. */
function verdictText(verdict: string | null, band: string[]): string {
  if (verdict) return VERDICTS[verdict] ?? verdict;
  const [low, high] = band.map((v) => VERDICTS[v]?.toLowerCase() ?? v);
  if (!low || !high || low === high) return VERDICTS[band[0] ?? ""] ?? "Not known";
  return `Between ${low} and ${high}`;
}

/**
 * Goals: a goal said or typed, restated for the owner to confirm; whether it is within reach (a
 * point chance up to 90 days, a band and why the evidence is thin beyond); the plan, week by week,
 * with and without it; its steps, the superseded one with what replaced it; then the goal as a
 * thread: what lies ahead, and what happened, newest first. Each goal has its address.
 */
export function GoalsPage() {
  const api = useApi();
  const { storeId } = useStore();
  const { goalId } = useParams();
  const navigate = useNavigate();
  const goals = useQuery({
    queryKey: ["goals", storeId],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/stores/{store_id}/goals", { params: { path: { store_id: storeId } } }),
      ),
  });
  const { ask, byText, byVoice } = useGoalAsk();

  const items = goals.data ?? [];
  const drafted = ask.state === "drafted" ? ask.goalId : null;
  // A goal just said opens at its address, to be confirmed there.
  useEffect(() => {
    if (drafted) void navigate(`/goals/${drafted}`);
  }, [drafted, navigate]);
  // The goal shown: the one at the address, else the one being followed (its plan accepted),
  // else a confirmed one, else a draft.
  const current =
    items.find((g) => g.goal_id === goalId) ??
    LEAD.map((status) => items.find((g) => g.status === status)).find((g) => g) ??
    items[0];
  const others = items.filter((g) => g !== current);

  return (
    <section aria-labelledby="goals-title" className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <h1 id="goals-title" className="text-title font-semibold text-ink">
          Goals
        </h1>
        <p className="text-body text-ink-muted">
          What you aim for, whether it is within reach, and the plan to get there.
        </p>
      </header>
      <section aria-label="Set a goal" className="flex flex-col gap-2">
        <Composer
          onSend={byText}
          onVoice={byVoice}
          label="Say or type a goal"
          placeholder="A goal, for example: 225,000 in net profit over the next three months"
        />
        <AskState ask={ask} />
      </section>
      {goals.isPending && <Skeleton rows={4} />}
      {goals.isError && <p className="text-body text-ink-muted">The goals could not be loaded.</p>}
      {goals.data && items.length === 0 && (
        <EmptyState title="No goal yet: say or type one above.">
          Say what you aim for, how much and by when. I restate it for you to confirm, tell you
          whether it is within reach, and propose a plan week by week.
        </EmptyState>
      )}
      {current && <GoalView key={current.goal_id} goal={current} />}
      {others.length > 0 && (
        <section aria-labelledby="other-goals" className="flex flex-col gap-3">
          <h2
            id="other-goals"
            className="border-b border-line pb-2.5 text-small font-medium text-ink-muted"
          >
            Other goals
          </h2>
          <ul className="flex flex-col divide-y divide-line">
            {others.map((g) => {
              const status = words(GOAL_STATUS, g.status);
              return (
                <li key={g.goal_id} className="flex items-center justify-between gap-3 py-3">
                  <span className="text-small text-ink">
                    <RichText text={g.restatement} facts={g.facts} names={g.names} />
                  </span>
                  <span className="flex shrink-0 items-center gap-2">
                    <StatusPill tone={status.tone}>{status.text}</StatusPill>
                    <Link
                      to={`/goals/${g.goal_id}`}
                      className="inline-flex h-9 items-center rounded-full px-3 text-small font-medium text-ink-muted transition-colors duration-150 hover:bg-subtle hover:text-ink"
                    >
                      Show
                    </Link>
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </section>
  );
}

function AskState({ ask }: { ask: ReturnType<typeof useGoalAsk>["ask"] }) {
  if (ask.state === "idle") return null;
  const heard = ask.heard && <span className="text-ink">“{ask.heard}”</span>;
  return (
    <p role="status" className="flex flex-col gap-1 text-small text-ink-muted">
      {heard}
      {ask.state === "working" && <span>Reading your goal…</span>}
      {ask.state === "drafted" && (
        <span>Here is your goal as I understood it: confirm it below.</span>
      )}
      {ask.state === "not_a_goal" && (
        <span>
          That does not read as a goal: say what, how much and by when.{" "}
          <Link to="/" className="text-accent-ink underline underline-offset-4">
            Ask other questions in the conversation
          </Link>
          .
        </span>
      )}
      {ask.state === "failed" && <span>The goal could not be read. Try again.</span>}
    </p>
  );
}

function GoalView({ goal }: { goal: Goal }) {
  const api = useApi();
  const open = useOpen();
  useHere({ kind: "goal", id: goal.goal_id, label: goalLabel(goal) });
  const queries = useQueryClient();
  const { storeId } = useStore();
  const path = { store_id: storeId, goal_id: goal.goal_id };
  const confirmed = goal.status !== "draft";
  const refresh = () => queries.invalidateQueries({ queryKey: ["goals", storeId] });

  const feasibility = useQuery({
    queryKey: ["goal-feasibility", storeId, goal.goal_id, goal.status],
    enabled: confirmed,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/stores/{store_id}/goals/{goal_id}/feasibility", { params: { path } }),
      ),
  });
  const plans = useQuery({
    queryKey: ["goal-plans", storeId, goal.goal_id, goal.status],
    enabled: confirmed,
    queryFn: () =>
      unwrap(api.GET("/api/v1/stores/{store_id}/goals/{goal_id}/plans", { params: { path } })),
  });
  const progress = useQuery({
    queryKey: ["goal-progress", storeId, goal.goal_id, goal.status],
    enabled: confirmed,
    queryFn: () =>
      unwrap(api.GET("/api/v1/stores/{store_id}/goals/{goal_id}/progress", { params: { path } })),
  });
  const confirm = useMutation({
    mutationFn: () =>
      unwrap(api.POST("/api/v1/stores/{store_id}/goals/{goal_id}/confirm", { params: { path } })),
    onSuccess: refresh,
  });
  const propose = useMutation({
    mutationFn: () =>
      unwrap(api.POST("/api/v1/stores/{store_id}/goals/{goal_id}/plans", { params: { path } })),
    onSuccess: () => queries.invalidateQueries({ queryKey: ["goal-plans", storeId, goal.goal_id] }),
  });

  const status = words(GOAL_STATUS, goal.status);
  const all = plans.data ?? [];
  const plan = all.find((p) => p.status === "accepted") ?? all.find((p) => p.status === "proposed");

  return (
    <article aria-label="Your goal" className="flex flex-col gap-12">
      <section
        className={cx(
          "flex flex-col gap-4",
          !confirmed && "rounded-card border border-line bg-surface p-5 shadow-float sm:p-6",
        )}
      >
        <div className="flex items-center justify-between gap-3">
          <h2 className="flex items-center gap-2 text-small font-medium text-ink-muted">
            Your goal
          </h2>
          <StatusPill tone={status.tone}>{status.text}</StatusPill>
        </div>
        <p className="max-w-[40ch] text-heading font-medium text-ink">
          <RichText text={goal.restatement} facts={goal.facts} names={goal.names} />
        </p>
        {!confirmed && goal.question && (
          <p className="text-label text-ink-muted">You said: “{goal.question}”</p>
        )}
        {!confirmed && (
          <div className="flex flex-wrap items-center gap-2.5">
            <Button
              className="h-9 px-4 text-small"
              disabled={confirm.isPending}
              onClick={() => {
                confirm.mutate();
              }}
            >
              Confirm this goal
            </Button>
            <span className="text-label text-ink-muted">
              Not quite it? Say or type it again above.
            </span>
          </div>
        )}
        {confirm.isError && (
          <p role="alert" className="text-small text-danger-ink">
            The goal could not be confirmed. Try again.
          </p>
        )}
      </section>
      {feasibility.data && <Reach feasibility={feasibility.data} />}
      {feasibility.isError && (
        <p className="text-body text-ink-muted">Whether it is within reach could not be loaded.</p>
      )}
      {confirmed && plans.data && !plan && (
        <div className="flex items-center gap-3">
          <Button
            className="h-9 px-4 text-small"
            disabled={propose.isPending}
            onClick={() => {
              propose.mutate();
            }}
          >
            Make a plan
          </Button>
          <span className="text-label text-ink-muted">
            I simulate the levers your store has and propose the steps that help most.
          </span>
        </div>
      )}
      {plan && (
        <PlanView
          goal={goal}
          plan={plan}
          feasibility={feasibility.data}
          progress={progress.data ?? []}
          onAccepted={refresh}
        />
      )}
      {confirmed && (
        <Thread
          goal={goal}
          plan={plan}
          feasibility={feasibility.data}
          progress={progress.data ?? []}
        />
      )}
      {confirmed && (
        <footer className="flex flex-wrap items-center gap-3 border-t border-line pt-6">
          <Button
            variant="secondary"
            className="h-9 px-4 text-small"
            onClick={() => {
              open.ask({ kind: "goal", id: goal.goal_id, label: goalLabel(goal) });
            }}
          >
            Ask about this goal
          </Button>
          <span className="text-label text-ink-muted">
            To change the target or the deadline, say or type the goal again above.
          </span>
        </footer>
      )}
    </article>
  );
}

/** Whether the goal is within reach: a point chance up to 90 days, a band beyond. */
function Reach({ feasibility: f }: { feasibility: Feasibility }) {
  const fact = (id: number | null | undefined) => (id == null ? undefined : f.facts[String(id)]);
  const chance = fact(f.probability_fact_id);
  const forecast = fact(f.forecast_fact_id);
  const gap = fact(f.gap_fact_id);
  return (
    <section aria-labelledby="reach-title" className="flex flex-col gap-4">
      <h2
        id="reach-title"
        className="border-b border-line pb-2.5 text-small font-medium text-ink-muted"
      >
        Within reach?
      </h2>
      <p className="text-title font-semibold text-ink">{verdictText(f.verdict, f.verdict_band)}</p>
      <VerdictBand band={f.verdict ? [f.verdict] : f.verdict_band} />
      {f.probability !== null && chance ? (
        <p className="text-small text-ink">
          <span className="text-ink-muted">Chance of reaching it: </span>
          <FactValue fact={chance} title="Chance of reaching the target" />
        </p>
      ) : (
        <p className="text-small text-ink-muted">
          Beyond 90 days I give no single chance: only the band it lies in.
        </p>
      )}
      {f.low_evidence.length > 0 && (
        <p className="text-small text-ink-muted">Low evidence: {f.low_evidence.join("; ")}.</p>
      )}
      <dl className="flex flex-col divide-y divide-line">
        {forecast && (
          <div className="flex flex-col gap-2 py-3">
            <dt className="text-small text-ink-muted">If nothing changes, at the deadline</dt>
            <dd>
              <RangeBar fact={forecast} title={forecast.name} />
            </dd>
          </div>
        )}
        {gap && (
          <div className="flex items-center justify-between gap-3 py-3">
            <dt className="text-small text-ink-muted">Gap to the target</dt>
            <dd className="text-small text-ink">
              <FactValue fact={gap} title={gap.name} />
            </dd>
          </div>
        )}
      </dl>
    </section>
  );
}

function PlanView({
  goal,
  plan,
  feasibility,
  progress,
  onAccepted,
}: {
  goal: Goal;
  plan: Plan;
  feasibility: Feasibility | undefined;
  progress: Progress[];
  onAccepted: () => Promise<void>;
}) {
  const api = useApi();
  const queries = useQueryClient();
  const { storeId } = useStore();
  const accept = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/stores/{store_id}/goals/{goal_id}/plans/{plan_id}/accept", {
          params: { path: { store_id: storeId, goal_id: goal.goal_id, plan_id: plan.plan_id } },
        }),
      ),
    onSuccess: async () => {
      await queries.invalidateQueries({ queryKey: ["decisions", storeId] });
      await onAccepted();
    },
  });
  const p = plan.payload as PlanPayload;
  const fact = (id: number | null | undefined): Fact | undefined =>
    id == null ? undefined : plan.facts[String(id)];
  const without = feasibility?.facts[String(feasibility.forecast_fact_id)];
  const withPlan = fact(p.outcome_fact_id);
  const chanceWithout = fact(p.probability_without_fact_id);
  const chanceWith = fact(p.probability_with_fact_id);
  const added = fact(p.profit_change_fact_id);
  const actuals = new Map(
    progress
      .filter((e) => e.kind === "weekly" && e.milestone_fact_id != null && e.actual_fact_id != null)
      .map((e) => [e.milestone_fact_id, e.facts[String(e.actual_fact_id)]] as const),
  );
  const weeks: FanWeek[] = (p.milestones ?? []).flatMap((m) => {
    const milestone = fact(m.fact_id);
    return milestone
      ? [{ day: m.day, label: formatDay(m.date), milestone, actual: actuals.get(m.fact_id) }]
      : [];
  });
  const revision = progress.findLast((e) => e.kind === "revision" && e.revision_proposed);

  return (
    <section aria-labelledby="plan-title" className="flex flex-col gap-6">
      <div className="flex items-center justify-between gap-3">
        <h2 id="plan-title" className="text-small font-medium text-ink-muted">
          The plan
        </h2>
        <StatusPill tone={plan.status === "accepted" ? "info" : "warning"}>
          {plan.status === "accepted" ? "Accepted" : "Proposed: waiting for you"}
        </StatusPill>
      </div>
      {weeks.length > 1 && (
        <FanChart
          weeks={weeks}
          target={fact(p.target_fact_id)}
          label="The plan week by week: the likely range of net profit to date, the most likely path, what was measured so far, and the target."
        />
      )}
      {(without ?? withPlan) && (
        <div className="flex flex-col gap-3">
          <h3 className="text-small font-medium text-ink">At the deadline</h3>
          <CompareRanges
            rows={[
              ...(without ? [{ label: "Without the plan", fact: without }] : []),
              ...(withPlan ? [{ label: "With the plan", fact: withPlan }] : []),
            ]}
          />
          {chanceWithout && chanceWith && (
            <>
              <h3 className="text-small font-medium text-ink">Chance of reaching the target</h3>
              <CompareRanges
                rows={[
                  { label: "Without the plan", fact: chanceWithout },
                  { label: "With the plan", fact: chanceWith },
                ]}
              />
            </>
          )}
          {added && (
            <p className="text-small text-ink">
              <span className="text-ink-muted">Profit the plan adds: </span>
              <FactValue fact={added} title={added.name} />
            </p>
          )}
        </div>
      )}
      {revision?.reason && (
        <p className="text-small text-ink">
          <span className="font-semibold">I propose to revise the plan: </span>
          <RichText text={revision.reason} facts={revision.facts} names={revision.names} />.
        </p>
      )}
      <section aria-labelledby="steps-title" className="flex flex-col gap-2">
        <h3 id="steps-title" className="text-small font-medium text-ink">
          Steps
        </h3>
        <ol className="flex flex-col divide-y divide-line">
          {plan.steps.map((step) => (
            <StepRow key={step.step_id} step={step} facts={plan.facts} names={plan.names} />
          ))}
        </ol>
      </section>
      {(p.experiments ?? []).length > 0 && (
        <section aria-labelledby="experiments-title" className="flex flex-col gap-2">
          <h3 id="experiments-title" className="text-small font-medium text-ink">
            Experiments to try
          </h3>
          <ul className="flex flex-col divide-y divide-line">
            {(p.experiments ?? []).map((e) => (
              <li key={e.lever} className="flex flex-col gap-1 py-3">
                <span className="text-label font-medium text-ink-muted">
                  {LEVERS[e.lever] ?? e.lever.replaceAll("_", " ")}
                </span>
                <span className="text-small text-ink">
                  <RichText text={e.summary} facts={plan.facts} names={plan.names} />
                </span>
                {e.experiment.cap && (
                  <span className="text-label text-ink-muted">
                    Limit: {e.experiment.cap}
                    {e.experiment.duration_days != null &&
                      `, over ${String(e.experiment.duration_days)} days`}
                    . Success: {e.experiment.success}.
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
      {(p.assumptions ?? []).length > 0 && (
        <details className="group text-small">
          <summary className="cursor-pointer text-ink-muted hover:text-ink">
            What this plan assumes
          </summary>
          <ul className="mt-2 flex list-disc flex-col gap-1 pl-5 text-ink-muted">
            {(p.assumptions ?? []).map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </details>
      )}
      {plan.status === "proposed" && (
        <div className="flex flex-wrap items-center gap-3">
          <Button
            className="h-9 px-4 text-small"
            disabled={accept.isPending}
            onClick={() => {
              accept.mutate();
            }}
          >
            Accept the plan
          </Button>
          <span className="text-label text-ink-muted">
            Each step that changes something still asks for your approval.
          </span>
        </div>
      )}
    </section>
  );
}

function StepRow({ step, facts, names }: { step: Step; facts: Facts; names: Names }) {
  const open = useOpen();
  const status = words(STEP_STATUS, step.status);
  const effect = step.effect_fact_id == null ? undefined : facts[String(step.effect_fact_id)];
  const replaced = step.status === "superseded";
  return (
    <li aria-label={`Step ${String(step.position)}`} className="flex flex-col gap-2 py-4">
      <div className="flex items-start justify-between gap-3">
        <p className={replaced ? "text-small text-ink-muted line-through" : "text-small text-ink"}>
          <RichText text={step.summary} facts={facts} names={names} />
        </p>
        <span className="shrink-0">
          <StatusPill tone={status.tone}>{status.text}</StatusPill>
        </span>
      </div>
      <p className="flex flex-wrap gap-x-4 gap-y-1 text-label text-ink-muted">
        <span>From {formatDay(step.due_date)}</span>
        {effect && (
          <span>
            Adds <FactValue fact={effect} title={effect.name} className="text-ink" />
          </span>
        )}
      </p>
      {replaced && step.decision_id && <ReplacedBy decisionId={step.decision_id} names={names} />}
      {step.status === "proposed" && step.decision_id && (
        <div>
          <Button
            className="h-9 px-4 text-small"
            onClick={() => {
              if (step.decision_id) open.decision(step.decision_id);
            }}
          >
            Review
          </Button>
        </div>
      )}
    </li>
  );
}

/** What replaced a superseded step: the decision that stood, by its label, and why. */
function ReplacedBy({ decisionId, names }: { decisionId: string; names: Names }) {
  const api = useApi();
  const { storeId } = useStore();
  const open = useOpen();
  const get = (id: string) =>
    unwrap(
      api.GET("/api/v1/stores/{store_id}/decisions/{decision_id}", {
        params: { path: { store_id: storeId, decision_id: id } },
      }),
    );
  const loser = useQuery({
    queryKey: ["decision", storeId, decisionId],
    queryFn: () => get(decisionId),
  });
  const winnerId = loser.data?.superseded_by ?? null;
  const winner = useQuery({
    queryKey: ["decision", storeId, winnerId],
    enabled: winnerId !== null,
    queryFn: () => get(winnerId ?? ""),
  });
  if (!winner.data) return null;
  const chosen =
    winner.data.options.find((o) => o.option_id === winner.data.approved_option_id) ??
    winner.data.options.find((o) => o.option_id === winner.data.recommended_option_id);
  return (
    <p className="flex flex-wrap items-center gap-x-2 text-small text-ink">
      <span className="text-ink-muted">Replaced by</span>
      <button
        type="button"
        className="cursor-pointer text-left font-medium underline decoration-ink-muted underline-offset-4 hover:text-accent-ink"
        onClick={() => {
          open.decision(winner.data.decision_id);
        }}
      >
        {chosen?.label ?? winner.data.label}
      </button>
      {loser.data?.superseded_reason && (
        <span className="text-label text-ink-muted">
          (<RichText text={loser.data.superseded_reason} facts={{}} names={names} />)
        </span>
      )}
    </p>
  );
}

/** The goal in a few words, for a conversation about it: its restatement, in plain text. */
function goalLabel(goal: Goal): string {
  const text = plainText(goal.restatement, goal.facts, goal.names).replace(/^Your goal: /, "");
  return text.charAt(0).toUpperCase() + text.slice(1).replace(/\.$/, "");
}

/** One moment of the thread: its store date, and its place within that day. */
interface Moment {
  key: string;
  day: string;
  /** The day as shown, when it is not `day` itself (the deadline: its last day included). */
  shown?: string;
  rank: number;
  title: string;
  pill?: { tone: Tone; text: string };
  body: ReactNode;
}

const newestFirst = (a: Moment, b: Moment) =>
  a.day === b.day ? b.rank - a.rank : a.day < b.day ? 1 : -1;

/**
 * The goal as a thread, newest first. Ahead, in dashes: the deadline, the checkpoints beyond 90
 * days, the steps still to come and the plan's next weeks. Then what happened: the weekly checks,
 * the revisions, the plan's steps as decisions (with where each stands now), the plan accepted
 * and the goal set.
 */
function Thread({
  goal,
  plan,
  feasibility,
  progress,
}: {
  goal: Goal;
  plan: Plan | undefined;
  feasibility: Feasibility | undefined;
  progress: Progress[];
}) {
  const decisions = useDecisions();
  const live = new Map((decisions.data?.items ?? []).map((d) => [d.decision_id, d]));
  const p = (plan?.payload ?? {}) as PlanPayload;
  const planFacts = plan?.facts ?? {};
  const names = plan?.names ?? goal.names;
  const planFact = (id: number | null | undefined) =>
    id == null ? undefined : planFacts[String(id)];
  const accepted = plan?.status === "accepted";
  const now = [goal.as_of, ...(accepted ? [plan.as_of] : []), ...progress.map((e) => e.as_of)]
    .sort()
    .at(-1);
  const after = (day: string) => now === undefined || day > now;

  const ahead: Moment[] = [];
  const target = goal.target_fact_id == null ? undefined : goal.facts[String(goal.target_fact_id)];
  ahead.push({
    key: "deadline",
    day: goal.deadline,
    shown: formatLastDay(goal.deadline),
    rank: 3,
    title: "Deadline",
    body: target && (
      <p className="text-small text-ink-muted">
        Target <FactValue fact={target} title={target.name} className="text-ink" />
      </p>
    ),
  });
  const thin = (feasibility?.low_evidence.length ?? 0) > 0;
  for (const c of (feasibility?.checkpoints ?? []) as unknown as Checkpoint[]) {
    const likely = feasibility?.facts[String(c.fact_id)];
    // The one at the deadline is the forecast Reach already shows.
    if (!likely || !after(c.date) || c.date >= goal.deadline) continue;
    ahead.push({
      key: `checkpoint-${String(c.day)}`,
      day: c.date,
      rank: 2,
      title: "Checkpoint",
      pill: thin ? { tone: "neutral", text: "Low evidence" } : undefined,
      body: (
        <p className="text-small text-ink-muted">
          Likely by then <FactValue fact={likely} title={likely.name} className="text-ink" />
        </p>
      ),
    });
  }
  if (accepted) {
    for (const step of plan.steps) {
      if (step.status !== "planned" || !after(step.due_date)) continue;
      ahead.push({
        key: step.step_id,
        day: step.due_date,
        rank: 1,
        title: `Step ${String(step.position)}`,
        body: (
          <p className="text-small text-ink-muted">
            <RichText text={step.summary} facts={planFacts} names={names} />
          </p>
        ),
      });
    }
    for (const m of (p.milestones ?? []).filter((m) => after(m.date)).slice(0, 2)) {
      const milestone = planFact(m.fact_id);
      if (!milestone) continue;
      ahead.push({
        key: `milestone-${String(m.day)}`,
        day: m.date,
        rank: 0,
        title: "Weekly check",
        body: (
          <p className="text-small text-ink-muted">
            Plan <FactValue fact={milestone} title={milestone.name} className="text-ink" />
          </p>
        ),
      });
    }
  }

  const past: Moment[] = [];
  past.push({
    key: "set",
    day: goal.as_of,
    rank: 0,
    title: "Goal set and confirmed",
    body: goal.question && <p className="text-small text-ink-muted">You said: “{goal.question}”</p>,
  });
  if (accepted) {
    const added = planFact(p.profit_change_fact_id);
    const chance = planFact(p.probability_with_fact_id);
    past.push({
      key: "plan",
      day: plan.as_of,
      rank: 1,
      title: "Plan accepted",
      body: (added ?? chance) && (
        <p className="flex flex-wrap gap-x-4 gap-y-1 text-small text-ink-muted">
          {added && (
            <span>
              Adds <FactValue fact={added} title={added.name} className="text-ink" />
            </span>
          )}
          {chance && (
            <span>
              Chance with it <FactValue fact={chance} title={chance.name} className="text-ink" />
            </span>
          )}
        </p>
      ),
    });
    for (const step of plan.steps) {
      if (!step.decision_id) continue;
      const decision = live.get(step.decision_id);
      const replaced = (decision?.status ?? step.status) === "superseded";
      past.push({
        key: step.step_id,
        day: step.due_date,
        rank: 2,
        title: `Step ${String(step.position)}`,
        pill: decision ? statusOf(decision.status) : words(STEP_STATUS, step.status),
        body: (
          <p className="flex flex-col gap-1 text-small">
            <span className={replaced ? "text-ink-muted line-through" : "text-ink"}>
              <RichText text={step.summary} facts={planFacts} names={names} />
            </span>
            <Link
              to={`/decisions/${step.decision_id}`}
              className="self-start rounded-sm text-label font-medium text-accent-ink underline-offset-4 hover:underline"
            >
              Open the decision
            </Link>
          </p>
        ),
      });
    }
  }
  for (const e of progress) {
    const fact = (id: number | null) => (id == null ? undefined : e.facts[String(id)]);
    const actual = fact(e.actual_fact_id);
    const milestone = fact(e.milestone_fact_id);
    const chance = fact(e.probability_fact_id);
    const revision = e.kind === "revision";
    past.push({
      key: e.progress_id,
      day: e.as_of,
      rank: revision ? 4 : 3,
      title: revision ? "Revision proposed" : "Weekly check",
      pill: e.status ? words(PROGRESS_STATUS, e.status) : undefined,
      body: (
        <>
          {(actual ?? milestone) && (
            <p className="flex flex-wrap gap-x-4 gap-y-1 text-small text-ink-muted">
              {actual && (
                <span>
                  Actual <FactValue fact={actual} title={actual.name} className="text-ink" />
                </span>
              )}
              {milestone && (
                <span>
                  Plan <FactValue fact={milestone} title={milestone.name} className="text-ink" />
                </span>
              )}
              {chance && (
                <span>
                  Chance now <FactValue fact={chance} title={chance.name} className="text-ink" />
                </span>
              )}
            </p>
          )}
          {e.reason && (
            <p className="text-label text-ink-muted">
              <RichText text={e.reason} facts={e.facts} names={{ ...names, ...e.names }} />
            </p>
          )}
        </>
      ),
    });
  }

  return (
    <section aria-labelledby="thread-title" className="flex flex-col gap-6">
      <h2
        id="thread-title"
        className="border-b border-line pb-2.5 text-small font-medium text-ink-muted"
      >
        The thread
      </h2>
      <Moments label="Ahead" moments={ahead.sort(newestFirst)} dashed />
      <Moments label="So far" moments={past.sort(newestFirst)} />
    </section>
  );
}

function Moments({
  label,
  moments,
  dashed = false,
}: {
  label: string;
  moments: Moment[];
  dashed?: boolean;
}) {
  if (moments.length === 0) return null;
  return (
    <section aria-label={label} className="flex flex-col gap-2">
      <h3 className="text-small font-medium text-ink">{label}</h3>
      <ol
        className={cx(
          "flex flex-col border-l pl-4",
          dashed ? "border-dashed border-line" : "border-line",
        )}
      >
        {moments.map((m) => (
          <li
            key={m.key}
            aria-label={`${m.shown ?? formatDay(m.day)}, ${m.title}`}
            className="flex flex-col gap-1.5 py-3"
          >
            <div className="flex items-center justify-between gap-3">
              <span className="flex flex-wrap items-baseline gap-x-2.5">
                <time className="font-mono text-label text-ink-muted">
                  {m.shown ?? formatDay(m.day)}
                </time>
                <span className="text-small font-medium text-ink">{m.title}</span>
              </span>
              {m.pill && <StatusPill tone={m.pill.tone}>{m.pill.text}</StatusPill>}
            </div>
            {m.body}
          </li>
        ))}
      </ol>
    </section>
  );
}
