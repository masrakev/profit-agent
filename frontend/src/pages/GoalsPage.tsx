import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { unwrap, type Schemas } from "@/api/client";
import { useApi } from "@/api/context";
import { CompareRanges } from "@/charts/CompareRanges";
import { FanChart, type FanWeek } from "@/charts/FanChart";
import { RangeBar } from "@/charts/RangeBar";
import { useOpen } from "@/conversation/open";
import { RichText, type Facts, type Names } from "@/conversation/RichText";
import { FactValue } from "@/facts/FactValue";
import type { Fact } from "@/facts/facts";
import { formatDay } from "@/format/dates";
import { useGoalAsk } from "@/goals/ask";
import { Composer } from "@/shell/Composer";
import { useStore } from "@/stores/store";
import { Button } from "@/ui/Button";
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
 * with and without it; its steps, the superseded one with what replaced it; and the weekly
 * progress, including the weeks that wait for the owner's approval.
 */
export function GoalsPage() {
  const api = useApi();
  const { storeId } = useStore();
  const [chosen, setChosen] = useState<string | null>(null);
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
  const current =
    items.find((g) => g.goal_id === (chosen ?? drafted)) ??
    items.find((g) => ["draft", "confirmed", "planned"].includes(g.status)) ??
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
      {goals.isPending && (
        <p className="h-40 animate-pulse rounded-card bg-subtle" aria-busy="true" />
      )}
      {goals.isError && <p className="text-body text-ink-muted">The goals could not be loaded.</p>}
      {goals.data && items.length === 0 && (
        <p className="text-body text-ink-muted">No goal yet: say or type one above.</p>
      )}
      {current && <GoalView key={current.goal_id} goal={current} />}
      {others.length > 0 && (
        <section aria-labelledby="other-goals" className="flex flex-col gap-3">
          <h2 id="other-goals" className="text-small font-semibold text-ink">
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
                    <Button
                      variant="ghost"
                      className="h-9 px-3 text-small"
                      onClick={() => {
                        setChosen(g.goal_id);
                      }}
                    >
                      Show
                    </Button>
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
    <article aria-label="Your goal" className="flex flex-col gap-8">
      <section className="flex flex-col gap-4 rounded-card border border-line bg-surface p-6 shadow-float">
        <div className="flex items-start justify-between gap-3">
          <h2 className="text-small font-semibold text-ink">Your goal</h2>
          <StatusPill tone={status.tone}>{status.text}</StatusPill>
        </div>
        <p className="text-body text-ink">
          <RichText text={goal.restatement} facts={goal.facts} names={goal.names} />
        </p>
        {goal.question && <p className="text-label text-ink-muted">You said: “{goal.question}”</p>}
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
      {progress.data && progress.data.length > 0 && (
        <Weekly entries={progress.data} names={plan?.names ?? {}} />
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
  const checkpoints = (f.checkpoints as unknown as Checkpoint[]).flatMap((c) => {
    const found = fact(c.fact_id);
    return found ? [{ ...c, fact: found }] : [];
  });
  return (
    <section aria-labelledby="reach-title" className="flex flex-col gap-4">
      <h2 id="reach-title" className="text-small font-semibold text-ink">
        Within reach?
      </h2>
      <p className="text-heading font-semibold tracking-tight text-ink">
        {verdictText(f.verdict, f.verdict_band)}
      </p>
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
      {checkpoints.length > 0 && (
        <section aria-label="Checkpoints" className="flex flex-col gap-2">
          <h3 className="text-small font-semibold text-ink">Checkpoints</h3>
          <ol className="flex flex-col border-l border-line pl-4">
            {checkpoints.map((c) => (
              <li key={c.day} className="flex justify-between gap-3 py-1.5 text-small">
                <span className="text-ink-muted">{formatDay(c.date)}</span>
                <FactValue fact={c.fact} title={c.fact.name} className="text-ink" />
              </li>
            ))}
          </ol>
        </section>
      )}
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
        <h2 id="plan-title" className="text-small font-semibold text-ink">
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
          <h3 className="text-small font-semibold text-ink">At the deadline</h3>
          <CompareRanges
            rows={[
              ...(without ? [{ label: "Without the plan", fact: without }] : []),
              ...(withPlan ? [{ label: "With the plan", fact: withPlan }] : []),
            ]}
          />
          {chanceWithout && chanceWith && (
            <>
              <h3 className="text-small font-semibold text-ink">Chance of reaching the target</h3>
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
        <h3 id="steps-title" className="text-small font-semibold text-ink">
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
          <h3 id="experiments-title" className="text-small font-semibold text-ink">
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

/** The goal's weeks: what was measured against the plan, and the weeks that wait for you. */
function Weekly({ entries, names }: { entries: Progress[]; names: Names }) {
  return (
    <section aria-labelledby="weekly-title" className="flex flex-col gap-2">
      <h2 id="weekly-title" className="text-small font-semibold text-ink">
        Week by week
      </h2>
      <ol className="flex flex-col divide-y divide-line">
        {entries.map((e) => {
          const fact = (id: number | null) => (id == null ? undefined : e.facts[String(id)]);
          const actual = fact(e.actual_fact_id);
          const milestone = fact(e.milestone_fact_id);
          const chance = fact(e.probability_fact_id);
          const status = e.status ? words(PROGRESS_STATUS, e.status) : null;
          return (
            <li
              key={e.progress_id}
              aria-label={`${formatDay(e.as_of)}, ${e.kind}`}
              className="flex flex-col gap-1.5 py-3"
            >
              <div className="flex items-center justify-between gap-3">
                <span className="text-small font-medium text-ink">{formatDay(e.as_of)}</span>
                {status ? (
                  <StatusPill tone={status.tone}>{status.text}</StatusPill>
                ) : (
                  e.revision_proposed && <StatusPill tone="info">Revision proposed</StatusPill>
                )}
              </div>
              {(actual ?? milestone) && (
                <p className="flex flex-wrap gap-x-4 gap-y-1 text-small text-ink-muted">
                  {actual && (
                    <span>
                      Actual <FactValue fact={actual} title={actual.name} className="text-ink" />
                    </span>
                  )}
                  {milestone && (
                    <span>
                      Plan{" "}
                      <FactValue fact={milestone} title={milestone.name} className="text-ink" />
                    </span>
                  )}
                  {chance && (
                    <span>
                      Chance now{" "}
                      <FactValue fact={chance} title={chance.name} className="text-ink" />
                    </span>
                  )}
                </p>
              )}
              {e.reason && (
                <p className="text-label text-ink-muted">
                  <RichText text={e.reason} facts={e.facts} names={{ ...names, ...e.names }} />
                </p>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
