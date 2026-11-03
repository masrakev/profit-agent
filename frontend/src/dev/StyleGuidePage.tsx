/**
 * Development build only: the components of page 1 laid out like the Figma frame "Style guide ·
 * Profit Agent", for side-by-side review. Every number on it is a fact of the signed-in store
 * (its overview and its most recent decision with options); nothing is made up for the catalogue.
 */
import { useQueries, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { unwrap, type Schemas } from "@/api/client";
import { useApi } from "@/api/context";
import { RangeBar } from "@/charts/RangeBar";
import { PermissionCard } from "@/decisions/PermissionCard";
import { estimateOf, factKey, type Fact } from "@/facts/facts";
import { FactValue } from "@/facts/FactValue";
import { VerifiedSeal } from "@/facts/VerifiedSeal";
import { formatPeriod } from "@/format/dates";
import { humanize } from "@/format/words";
import { Composer } from "@/shell/Composer";
import { useStore } from "@/stores/store";
import { BrandMark } from "@/ui/BrandMark";
import { Bubble } from "@/ui/Bubble";
import { Button } from "@/ui/Button";
import { cx } from "@/ui/cx";
import { StatusPill } from "@/ui/StatusPill";

type Decision = Schemas["DecisionView"];

const SWATCHES = [
  ["Background", "--pa-canvas"],
  ["Surface", "--pa-surface"],
  ["Primary text", "--pa-ink"],
  ["Secondary text", "--pa-ink-muted"],
  ["Divider", "--pa-line"],
  ["Primary blue", "--pa-accent"],
  ["Owner bubble", "--pa-bubble-owner"],
  ["Assistant bubble", "--pa-subtle"],
  ["Blue text (AA)", "--pa-accent-ink"],
  ["Blue fill (AA)", "--pa-accent-fill"],
] as const;

const STATUS_BARS = [
  ["critical", "bg-danger"],
  ["warning", "bg-warning"],
  ["good", "bg-good"],
  ["info", "bg-accent-mark"],
] as const;

function useCatalogueFacts() {
  const api = useApi();
  const { storeId } = useStore();
  const overview = useQuery({
    queryKey: ["overview", storeId],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/stores/{store_id}/overview", { params: { path: { store_id: storeId } } }),
      ),
  });
  const decisions = useQuery({
    queryKey: ["decisions", storeId, "catalogue"],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/stores/{store_id}/decisions", {
          params: { path: { store_id: storeId }, query: { limit: 20 } },
        }),
      ),
  });
  const comparable = (decisions.data?.items ?? []).filter(
    (item) => item.options.filter((option) => option.impact_fact_id != null).length > 1,
  );
  const decision = comparable.find((item) => item.status === "proposed") ?? comparable[0];
  const impactIds = [
    ...(decision?.options ?? []).map((option) => option.impact_fact_id),
    decision?.do_nothing.impact_fact_id,
  ].flatMap((id) => (id == null ? [] : [id]));
  const impacts = useQueries({
    queries: impactIds.map((factId) => ({
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
  const facts = Object.values(overview.data?.facts ?? {});
  const byId = new Map(
    impacts.flatMap((query) => (query.data ? [query.data.fact] : [])).map((f) => [f.fact_id, f]),
  );
  return {
    exact: facts.find((fact) => fact.kind === "exact" && fact.metric === "net_profit"),
    estimate: facts.find((fact) => estimateOf(fact) !== null),
    decision,
    fact: (factId: number | null | undefined) =>
      factId == null ? null : (byId.get(factId) ?? null),
    pending: overview.isPending || decisions.isPending,
  };
}

export function StyleGuidePage() {
  const data = useCatalogueFacts();
  return (
    <main className="mx-auto flex w-full max-w-[1280px] flex-col gap-7 bg-canvas px-12 py-12">
      <header className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <BrandMark named />
          <StatusPill tone="info">Profit Agent / Foundations</StatusPill>
        </div>
        <h1 className="text-title font-semibold text-ink">
          A calm workspace for clearer decisions.
        </h1>
        <p className="text-label text-ink-muted">
          Component catalogue · development build · numbers from your store
        </p>
      </header>

      <div className="grid gap-5 md:grid-cols-2">
        <Palette theme="light" title="Light · Calm clarity" />
        <Palette theme="dark" title="Dark · Quiet contrast" />
      </div>

      <div className="grid gap-5 md:grid-cols-2">
        <Card title="Typography / Figtree">
          <dl className="grid grid-cols-[32px_1fr] items-baseline gap-x-4 gap-y-3 text-ink">
            <Sample size="28" className="text-title font-semibold">
              Title · A little more clarity
            </Sample>
            <Sample size="20" className="text-heading font-semibold">
              Card title · Your next best step
            </Sample>
            <Sample size="15" className="text-body">
              Body · Short, plain sentences.
            </Sample>
            <Sample size="13" className="text-small">
              Secondary · Depth when you need it.
            </Sample>
            <Sample size="12" className="text-label uppercase">
              Label · data up to date
            </Sample>
          </dl>
          <p className="flex flex-wrap gap-3 text-small text-ink-muted">
            Numbers from your store:
            {data.exact && <FactValue fact={data.exact} className="text-ink" />}
            {data.estimate && <FactValue fact={data.estimate} className="text-ink" />}
          </p>
        </Card>

        <Card title="Actions / Clear permission">
          <div className="flex flex-wrap gap-2.5">
            <Button>Approve</Button>
            <Button variant="secondary">Not now</Button>
            <Button variant="ghost">See proof</Button>
            <Button variant="danger">Delete store</Button>
          </div>
          <div className="flex flex-wrap gap-2">
            <StatusPill tone="info">Waiting for you</StatusPill>
            <StatusPill tone="good">Measured</StatusPill>
            <StatusPill tone="warning">Watch</StatusPill>
            <StatusPill tone="critical">Needs attention</StatusPill>
          </div>
          <div className="grid grid-cols-4 gap-3 text-caption text-ink-muted">
            {STATUS_BARS.map(([name, colour]) => (
              <span key={name} className="flex flex-col gap-1.5">
                <span className={cx("h-1 rounded-full", colour)} />
                {name}
              </span>
            ))}
          </div>
          <p className="text-caption text-ink-muted">
            20 px cards and composer · 18 px bubbles · pill buttons · 1.5 px line icons · shadows
            only for floating surfaces
          </p>
        </Card>
      </div>

      <div className="grid items-start gap-5 md:grid-cols-2">
        <div className="flex flex-col gap-5">
          <Card
            title="Estimates are always ranges"
            seal={data.estimate && <VerifiedSeal fact={data.estimate} />}
          >
            {data.estimate ? <RangeBar fact={data.estimate} /> : <Missing pending={data.pending} />}
            <p className="text-caption text-ink-muted">
              Never hide uncertainty behind a single number.
            </p>
          </Card>
          <Bubble from="owner">What should I do next?</Bubble>
          <Bubble from="agent">
            I found one opportunity. Let’s check the numbers before changing anything.
          </Bubble>
          <Composer />
          <div className="flex flex-col gap-2 px-3 py-4">
            <p className="text-heading font-semibold text-ink">
              Friendly. Confident. Never alarming.
            </p>
            <p className="text-small text-ink-muted">
              Start with what matters. Show the evidence on demand. Ask before acting. Measure what
              happened.
            </p>
          </div>
        </div>
        <div className="flex flex-col gap-3">
          <p className="text-label font-semibold text-ink">
            First approval / No standing permission
          </p>
          {data.decision ? (
            <DecisionCard decision={data.decision} fact={data.fact} />
          ) : (
            <Card title="Permission card">
              <Missing pending={data.pending} />
            </Card>
          )}
        </div>
      </div>

      <section
        data-theme="dark"
        aria-label="Dark theme sample"
        className="grid gap-5 rounded-card bg-canvas p-6 text-ink md:grid-cols-2"
      >
        <div className="flex flex-col gap-4">
          <h2 className="text-heading font-semibold">Dark / Same rhythm, softer light</h2>
          <div className="flex flex-wrap items-center gap-2.5">
            <Button>Approve</Button>
            <Button variant="secondary">Not now</Button>
            <StatusPill tone="info">Possible</StatusPill>
          </div>
          {data.estimate && <RangeBar fact={data.estimate} />}
        </div>
        <div className="flex flex-col gap-4">
          <Bubble from="owner">Keep me in control.</Bubble>
          <Composer />
        </div>
      </section>
    </main>
  );
}

function DecisionCard({
  decision,
  fact,
}: {
  decision: Decision;
  fact: (factId: number | null | undefined) => Fact | null;
}) {
  const recommended = decision.options.find(
    (option) => option.option_id === decision.recommended_option_id,
  );
  const zero = fact(decision.do_nothing.impact_fact_id);
  const period = zero && formatPeriod(zero.period_start, zero.period_end);
  return (
    <PermissionCard
      question={decision.label}
      comparedWith={
        period ? `Compared with doing nothing, ${period}` : "Compared with doing nothing"
      }
      options={decision.options.map((option) => ({
        id: option.option_id,
        label: option.label,
        impact: fact(option.impact_fact_id),
        recommended: option.option_id === decision.recommended_option_id,
      }))}
      baseline={{ label: decision.do_nothing.label, impact: zero }}
      safety={`Safety checks: ${humanize(recommended?.reversibility ?? "reversible")} · nothing changes without your approval.`}
      onApprove={() => undefined}
      onDecline={() => undefined}
    />
  );
}

function Palette({ theme, title }: { theme: "light" | "dark"; title: string }) {
  const panel = useRef<HTMLElement>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  useEffect(() => {
    const element = panel.current;
    if (!element) return;
    const style = getComputedStyle(element);
    setValues(
      Object.fromEntries(
        SWATCHES.map(([, token]) => [token, style.getPropertyValue(token).trim().toUpperCase()]),
      ),
    );
  }, []);
  return (
    <section
      ref={panel}
      data-theme={theme}
      aria-label={title}
      className="flex flex-col gap-5 rounded-card border border-line bg-surface p-6 text-ink"
    >
      <h2 className="text-heading font-semibold">{title}</h2>
      <ul className="grid grid-cols-2 gap-x-6 gap-y-4">
        {SWATCHES.map(([name, token]) => (
          <li key={token} className="flex items-center gap-3">
            <span
              aria-hidden="true"
              className="size-9 shrink-0 rounded-mark border border-line"
              style={{ backgroundColor: `var(${token})` }}
            />
            <span className="flex flex-col text-caption">
              <span className="text-ink">{name}</span>
              <span className="text-ink-muted">{values[token] ?? ""}</span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Card({ title, seal, children }: { title: string; seal?: ReactNode; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-5 rounded-card border border-line bg-surface p-6">
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-heading font-semibold text-ink">{title}</h2>
        {seal}
      </div>
      {children}
    </section>
  );
}

function Sample({
  size,
  className,
  children,
}: {
  size: string;
  className: string;
  children: ReactNode;
}) {
  return (
    <>
      <dt className="text-caption text-ink-muted">{size}</dt>
      <dd className={className}>{children}</dd>
    </>
  );
}

function Missing({ pending }: { pending: boolean }) {
  return (
    <p className="text-small text-ink-muted">
      {pending
        ? "Loading your store’s numbers…"
        : "Your store has no such numbers yet: run make demo-seed."}
    </p>
  );
}
