import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { useOpen } from "./open";
import { ApiError, unwrap, type Schemas } from "@/api/client";
import { useApi } from "@/api/context";
import { PermissionCard } from "@/decisions/PermissionCard";
import { factKey, type Fact } from "@/facts/facts";
import { formatPeriod } from "@/format/dates";
import { useStore } from "@/stores/store";
import { Button } from "@/ui/Button";
import { AgentMark } from "@/ui/AgentMark";
import { Icon } from "@/ui/Icon";
import { STATUS } from "@/decisions/status";
import { StatusPill, type Tone } from "@/ui/StatusPill";

type Decision = Schemas["DecisionView"];
type Option = Decision["options"][number];
type Preview = Schemas["Preview"];
type Policy = Schemas["PolicyResult"];

const WAITING = new Set(["approved", "executing"]);
const PREVIEWED = new Set(["pause_campaign", "resume_campaign", "change_budget"]);

/** The policy checks an option's actions would meet now (a preview: nothing is done). */
function previews(option: Option | undefined): Preview[] {
  return (option?.actions ?? []).flatMap((action) => {
    const kind = action["kind"];
    const campaign = action["entity"];
    if (typeof kind !== "string" || !PREVIEWED.has(kind) || typeof campaign !== "string") {
      return [];
    }
    const change = action["change"];
    return [
      {
        kind: kind as Preview["kind"],
        campaign_id: campaign,
        change: typeof change === "string" ? change : null,
      },
    ];
  });
}

function safetyText(option: Option | undefined, checks: Policy[] | undefined): string {
  const blocked = checks?.find((check) => !check.allowed);
  if (blocked) return `Blocked by a safety check: ${blocked.reason}.`;
  const undo =
    option?.reversibility === "reversible"
      ? " · reversible · you can undo it anytime"
      : option?.reversibility === "prepare_only"
        ? " · nothing is changed for you: it is prepared for you to carry out"
        : "";
  return checks ? `Safety checks passed: within your limits${undo}.` : "Checking your limits…";
}

function problemText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "superseded") return "A newer decision replaced this one.";
    if (error.code === "expired") return "This decision expired before it was decided.";
    if (error.code === "already_decided") return "This decision was already decided.";
    if (error.code === "not_executable") return "This option cannot be carried out automatically.";
  }
  return "Your answer could not be sent. Try again in a moment.";
}

/**
 * A decision in the conversation: the agent asks before it acts. Proposed, it is the permission
 * card (each option with its range, "do nothing", the safety checks, Approve and Not now); once
 * answered it follows the decision live, through execution, to the platform's state read back.
 */
export function DecisionMessage({
  decisionId,
  headless = false,
}: {
  decisionId: string;
  /** Inside a decision's own page: what happened, without the title the page already shows. */
  headless?: boolean;
}) {
  const api = useApi();
  const { storeId } = useStore();
  const queries = useQueryClient();
  const open = useOpen();
  const key = ["decision", storeId, decisionId];
  const path = { store_id: storeId, decision_id: decisionId };

  const decision = useQuery({
    queryKey: key,
    queryFn: () =>
      unwrap(api.GET("/api/v1/stores/{store_id}/decisions/{decision_id}", { params: { path } })),
    refetchInterval: (query) => (WAITING.has(query.state.data?.status ?? "") ? 2000 : false),
  });
  const data = decision.data;
  const recommended = data?.options.find((o) => o.option_id === data.recommended_option_id);

  const ids = [
    ...(data?.options ?? []).map((o) => o.impact_fact_id),
    data?.do_nothing.impact_fact_id,
  ].flatMap((id) => (id == null ? [] : [id]));
  const factQueries = useQueries({
    queries: ids.map((factId) => ({
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
  const fact = (id: number | null | undefined) => (id == null ? null : (facts.get(id) ?? null));

  const checks = useQuery({
    queryKey: ["safety", storeId, decisionId, recommended?.option_id],
    enabled: data?.status === "proposed" && recommended !== undefined,
    queryFn: () =>
      Promise.all(
        previews(recommended).map((body) =>
          unwrap(
            api.POST("/api/v1/stores/{store_id}/policy/preview", {
              params: { path: { store_id: storeId } },
              body,
            }),
          ),
        ),
      ),
  });

  const settle = async (result: Decision | undefined) => {
    if (result) queries.setQueryData(key, result);
    await queries.invalidateQueries({ queryKey: key });
  };
  // When its status moves on (approved, executing, executed), the lists that show it follow.
  const status = data?.status;
  const seen = useRef(status);
  useEffect(() => {
    if (status === undefined || seen.current === status) return;
    const first = seen.current === undefined;
    seen.current = status;
    if (!first) void queries.invalidateQueries({ queryKey: ["decisions", storeId] });
  }, [queries, status, storeId]);
  const approve = useMutation({
    mutationFn: (optionId: string) =>
      unwrap(
        api.POST("/api/v1/stores/{store_id}/decisions/{decision_id}/approve", {
          params: { path },
          body: { option_id: optionId },
        }),
      ),
    onSuccess: settle,
    onError: () => settle(undefined),
  });
  const decline = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/stores/{store_id}/decisions/{decision_id}/reject", { params: { path } }),
      ),
    onSuccess: settle,
    onError: () => settle(undefined),
  });

  if (decision.isPending) return <p className="h-24 animate-pulse rounded-card bg-subtle" />;
  if (decision.isError) {
    return <p className="text-body text-ink-muted">This decision could not be loaded.</p>;
  }
  const d = decision.data;
  const zero = fact(d.do_nothing.impact_fact_id);
  const period = zero && formatPeriod(zero.period_start, zero.period_end);
  const failure = approve.error ?? decline.error;

  if (d.status === "proposed") {
    return (
      <div className="flex flex-col gap-3">
        <PermissionCard
          question={d.label}
          comparedWith={
            period ? `Compared with doing nothing, ${period}` : "Compared with doing nothing"
          }
          options={d.options.map((option) => ({
            id: option.option_id,
            label: option.label,
            impact: fact(option.impact_fact_id),
            recommended: option.option_id === d.recommended_option_id,
          }))}
          baseline={{ label: d.do_nothing.label, impact: zero }}
          safety={safetyText(recommended, checks.data)}
          blocked={checks.data?.some((check) => !check.allowed) ?? false}
          onApprove={() => {
            approve.mutate(d.recommended_option_id);
          }}
          onDecline={() => {
            decline.mutate();
          }}
          pending={approve.isPending || decline.isPending}
        />
        {failure && (
          <p role="alert" className="text-small text-danger-ink">
            {problemText(failure)}
          </p>
        )}
      </div>
    );
  }
  return <Outcome decision={d} option={recommended} onOpen={open.decision} headless={headless} />;
}

/** A decided decision: what happened to it, and what the platform reports now. */
function Outcome({
  decision,
  option,
  onOpen,
  headless,
}: {
  decision: Decision;
  option: Option | undefined;
  onOpen: (decisionId: string) => void;
  headless: boolean;
}) {
  const api = useApi();
  const { storeId } = useStore();
  const chosen =
    decision.options.find((o) => o.option_id === decision.approved_option_id) ?? option;
  const done = ["executed", "measured", "failed"].includes(decision.status);
  const actions = useQuery({
    queryKey: ["journal", storeId, decision.decision_id, decision.status],
    enabled: done,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/stores/{store_id}/journal", {
          params: { path: { store_id: storeId }, query: { limit: 200 } },
        }),
      ),
    select: (page) =>
      page.items.filter(
        (entry) =>
          entry.kind === "action" &&
          (entry.summary as { decision_id?: unknown }).decision_id === decision.decision_id,
      ),
  });
  const status = STATUS[decision.status] ?? { tone: "neutral" as Tone, text: decision.status };
  const superseded = decision.status === "superseded";

  return (
    <article aria-label={decision.label} className="flex flex-col gap-4 rounded-card bg-subtle p-5">
      <header className="flex items-start gap-3">
        {headless ? (
          <span className="flex-1 text-small font-medium text-ink-muted">Where it stands</span>
        ) : (
          <>
            <AgentMark size="sm" className="mt-1" />
            <h3
              className={`flex-1 text-body font-medium text-ink ${superseded ? "line-through" : ""}`}
            >
              {chosen && decision.approved_option_id ? chosen.label : decision.label}
            </h3>
          </>
        )}
        <span role="status">
          <StatusPill tone={status.tone}>{status.text}</StatusPill>
        </span>
      </header>
      {(decision.status === "approved" || decision.status === "executing") && (
        <p className="text-body text-ink-muted">
          You approved it. It is being carried out within your caps; this updates by itself.
        </p>
      )}
      {done && <ReadBack entries={actions.data} failed={decision.status === "failed"} />}
      {decision.status === "rejected" && (
        <p className="text-body text-ink-muted">Not now: nothing changed.</p>
      )}
      {decision.status === "expired" && (
        <p className="text-body text-ink-muted">Nobody approved it in time: nothing changed.</p>
      )}
      {superseded && (
        <div className="flex flex-col items-start gap-3">
          <p className="text-body text-ink-muted">
            Replaced by a newer decision
            {decision.superseded_reason ? `: ${decision.superseded_reason}` : "."}
          </p>
          {decision.superseded_by && (
            <Button
              variant="secondary"
              onClick={() => {
                onOpen(decision.superseded_by ?? "");
              }}
            >
              See the decision that replaced it
            </Button>
          )}
        </div>
      )}
    </article>
  );
}

type Entry = Schemas["JournalEntry"];

/** The platform's state after the action, as the executor read it back. */
function ReadBack({ entries, failed }: { entries: Entry[] | undefined; failed: boolean }) {
  if (!entries) return <p className="text-body text-ink-muted">Reading the platform back…</p>;
  if (entries.length === 0) {
    return <p className="text-body text-ink-muted">No action has been recorded yet.</p>;
  }
  return (
    <ul className="flex flex-col gap-2">
      {entries.map((entry) => {
        const summary = entry.summary as {
          kind?: unknown;
          status?: unknown;
          after?: { status?: unknown } | null;
          error?: unknown;
          provider?: unknown;
        };
        const state = typeof summary.after?.status === "string" ? summary.after.status : null;
        const platform = summary.provider === "meta" ? "Meta Ads" : "The ad platform";
        return (
          <li key={entry.id} className="flex items-start gap-2 text-body text-ink">
            <Icon
              name={failed ? "x" : "circle-check"}
              size={16}
              className={failed ? "mt-1 text-danger-ink" : "mt-1 text-good-ink"}
            />
            <span>
              {failed
                ? `It could not be carried out${typeof summary.error === "string" ? `: ${summary.error}` : "."}`
                : state
                  ? `${platform} reports the campaign ${state.toLowerCase()}.`
                  : `${platform} carried it out.`}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
