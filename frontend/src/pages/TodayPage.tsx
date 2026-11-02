import { useQuery } from "@tanstack/react-query";

import { unwrap, type Schemas } from "@/api/client";
import { useApi } from "@/api/context";
import { DriverBars } from "@/charts/DriverBars";
import { DocumentSections } from "@/conversation/DocumentSections";
import { FactValue } from "@/facts/FactValue";
import { VerifiedSeal } from "@/facts/VerifiedSeal";
import { formatPeriod } from "@/format/dates";
import { useStore } from "@/stores/store";

type Bridge = Schemas["Bridge"];

/**
 * Today: the store's day assembled now from facts (the picture, what needs the owner, the pending
 * decisions) and what moved net profit this week, driver by driver.
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
    <section aria-labelledby="today-title" className="flex flex-col gap-6">
      <header className="flex flex-col gap-2">
        <h1 id="today-title" className="text-title font-semibold text-ink">
          Today
        </h1>
        {overview.data && <p className="text-body text-ink-muted">{overview.data.headline}</p>}
      </header>
      {overview.isPending && (
        <p className="h-40 animate-pulse rounded-card bg-subtle" aria-busy="true" />
      )}
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
    <section
      aria-labelledby="bridge-title"
      className="flex flex-col gap-5 rounded-card border border-line bg-surface p-6 shadow-float"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h2 id="bridge-title" className="text-small font-semibold text-ink">
            What moved your net profit
          </h2>
          {period && before && (
            <p className="text-label text-ink-muted">
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
