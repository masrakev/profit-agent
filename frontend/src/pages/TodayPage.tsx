import { useQuery } from "@tanstack/react-query";

import { unwrap, type Schemas } from "@/api/client";
import { useApi } from "@/api/context";
import { DriverBars } from "@/charts/DriverBars";
import { DocumentSections } from "@/conversation/DocumentSections";
import { FactValue } from "@/facts/FactValue";
import { VerifiedSeal } from "@/facts/VerifiedSeal";
import { formatPeriod } from "@/format/dates";
import { useStore } from "@/stores/store";
import { AgentMark } from "@/ui/AgentMark";
import { Skeleton } from "@/ui/Skeleton";

type Bridge = Schemas["Bridge"];

/**
 * Today, as an editorial brief: the day's headline, then what needs the owner, the picture and the
 * money at stake, the pending decisions as rows (all assembled now from facts), and what moved net
 * profit this week, driver by driver.
 */
export function TodayPage() {
  const api = useApi();
  const { storeId } = useStore();
  const path = { params: { path: { store_id: storeId } } };
  const overview = useQuery({
    queryKey: ["overview", storeId],
    queryFn: () => unwrap(api.GET("/api/v1/stores/{store_id}/overview", path)),
  });
  const bridge = useQuery({
    queryKey: ["profit-bridge", storeId],
    queryFn: () => unwrap(api.GET("/api/v1/stores/{store_id}/profit-bridge", path)),
  });

  return (
    <section aria-labelledby="today-title" className="flex flex-col gap-10">
      <header className="flex flex-col gap-4">
        <h1
          id="today-title"
          className="flex items-center gap-2 font-mono text-label font-normal text-ink-muted"
        >
          <AgentMark size="sm" />
          Today
        </h1>
        {overview.data && (
          <p className="max-w-[24ch] text-title font-semibold text-ink md:text-proof">
            {overview.data.headline}
          </p>
        )}
      </header>
      {overview.isPending && <Skeleton rows={4} />}
      {overview.isError && (
        <p className="text-body text-ink-muted">Today’s overview could not be loaded.</p>
      )}
      {overview.data && <DocumentSections document={overview.data} pictureTitle="Your store" />}
      {bridge.data?.change && <ProfitBridge bridge={bridge.data} />}
      {bridge.isError && (
        <p className="text-body text-ink-muted">What moved your profit could not be loaded.</p>
      )}
    </section>
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
