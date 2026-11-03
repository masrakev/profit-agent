import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { unwrap, type Schemas } from "@/api/client";
import { useApi } from "@/api/context";
import { DriverBars } from "@/charts/DriverBars";
import { Brief } from "@/conversation/Brief";
import { DocumentSections } from "@/conversation/DocumentSections";
import { useMorningBrief } from "@/conversation/morningBrief";
import { RichText } from "@/conversation/RichText";
import { FactValue } from "@/facts/FactValue";
import { VerifiedSeal } from "@/facts/VerifiedSeal";
import { formatPeriod } from "@/format/dates";
import { useStore } from "@/stores/store";
import { AgentMark } from "@/ui/AgentMark";
import { Section } from "@/ui/Section";
import { Skeleton } from "@/ui/Skeleton";
import { StatusPill, type Tone } from "@/ui/StatusPill";

type Bridge = Schemas["Bridge"];

const GOAL_STATUS: Record<string, { tone: Tone; text: string }> = {
  draft: { tone: "warning", text: "Waiting for your confirmation" },
  confirmed: { tone: "info", text: "Confirmed" },
  planned: { tone: "info", text: "Following its plan" },
};

/**
 * Home: the day in one place. The morning brief (its send time, what matters, the money at stake,
 * the decisions waiting), the goals in progress, and what moved net profit this week. With no
 * brief yet, the store's day as assembled now. Questions asked here open in Conversations.
 */
export function HomePage() {
  const api = useApi();
  const { storeId } = useStore();
  const path = { params: { path: { store_id: storeId } } };
  const morning = useMorningBrief();
  const bridge = useQuery({
    queryKey: ["profit-bridge", storeId],
    queryFn: () => unwrap(api.GET("/api/v1/stores/{store_id}/profit-bridge", path)),
  });

  return (
    <section aria-label="Home" className="flex flex-col gap-12">
      {morning.none ? <Overview /> : <Brief />}
      <GoalsInProgress />
      {bridge.data?.change && <ProfitBridge bridge={bridge.data} />}
      {bridge.isError && (
        <p className="text-body text-ink-muted">What moved your profit could not be loaded.</p>
      )}
    </section>
  );
}

/** The store's day assembled now from facts, for a store that has no morning brief yet. */
function Overview() {
  const api = useApi();
  const { storeId } = useStore();
  const overview = useQuery({
    queryKey: ["overview", storeId],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/stores/{store_id}/overview", { params: { path: { store_id: storeId } } }),
      ),
  });
  if (overview.isPending) return <Skeleton rows={4} />;
  if (overview.isError) {
    return <p className="text-body text-ink-muted">Today’s overview could not be loaded.</p>;
  }
  return (
    <article aria-label="Today" className="flex flex-col gap-10">
      <header className="flex flex-col gap-4">
        <p className="flex items-center gap-2 font-mono text-label text-ink-muted">
          <AgentMark size="sm" />
          Today
        </p>
        <h1 className="max-w-[24ch] text-title font-semibold text-ink md:text-proof">
          {overview.data.headline}
        </h1>
      </header>
      <DocumentSections document={overview.data} pictureTitle="Your store" />
    </article>
  );
}

/** The goals being followed, each a row that opens it. */
function GoalsInProgress() {
  const api = useApi();
  const { storeId } = useStore();
  const goals = useQuery({
    queryKey: ["goals", storeId],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/stores/{store_id}/goals", { params: { path: { store_id: storeId } } }),
      ),
  });
  // The goal being followed first, then confirmed ones, then drafts.
  const order = Object.keys(GOAL_STATUS).reverse();
  const active = (goals.data ?? [])
    .filter((g) => g.status in GOAL_STATUS)
    .sort((a, b) => order.indexOf(a.status) - order.indexOf(b.status));
  if (active.length === 0) return null;
  return (
    <Section
      title="Your goals"
      aside={
        <Link to="/goals" className="rounded-md text-small text-ink-muted hover:text-ink">
          All goals
        </Link>
      }
    >
      <ul className="flex flex-col" data-stagger>
        {active.map((g) => {
          const status = GOAL_STATUS[g.status] ?? { tone: "neutral" as Tone, text: g.status };
          return (
            <li key={g.goal_id} className="border-b border-line">
              <Link
                to="/goals"
                className="flex flex-col gap-2 rounded-md py-4 hover:bg-subtle/60 sm:flex-row sm:items-start sm:justify-between sm:gap-4"
              >
                <span className="min-w-0 text-body text-ink">
                  <RichText text={g.restatement} facts={g.facts} names={g.names} />
                </span>
                <StatusPill tone={status.tone}>{status.text}</StatusPill>
              </Link>
            </li>
          );
        })}
      </ul>
    </Section>
  );
}

function ProfitBridge({ bridge }: { bridge: Bridge }) {
  const change = bridge.change;
  if (!change) return null;
  const period = formatPeriod(bridge.period_start, bridge.period_end);
  const before = formatPeriod(bridge.baseline_start, bridge.baseline_end);
  return (
    <section aria-labelledby="bridge-title" className="flex flex-col gap-5">
      <div className="flex items-start justify-between gap-3 border-b border-line pb-2.5">
        <div className="flex flex-col gap-1">
          <h2 id="bridge-title" className="text-small font-medium text-ink-muted">
            What moved your net profit
          </h2>
          {period && before && (
            <p className="font-mono text-label text-ink-muted">
              {period}, against {before}
            </p>
          )}
        </div>
        <VerifiedSeal fact={change} />
      </div>
      <p className="text-body text-ink">
        {change.name}: <FactValue fact={change} title={change.name} className="font-semibold" />
      </p>
      {bridge.drivers.length > 0 && <DriverBars drivers={bridge.drivers} />}
      {bridge.drivers.length > 0 && bridge.drivers.every((d) => d.significant === false) && (
        <p className="text-label text-ink-muted">
          No driver stands out from the store’s usual week-to-week variation.
        </p>
      )}
    </section>
  );
}
