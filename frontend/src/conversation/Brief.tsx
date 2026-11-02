import { useQuery } from "@tanstack/react-query";

import { DocumentSections } from "./DocumentSections";
import { RichText } from "./RichText";
import { unwrap } from "@/api/client";
import { useApi } from "@/api/context";
import { formatTime, formatWeekday } from "@/format/dates";
import { useStore } from "@/stores/store";

/** The latest daily brief: what the store's day looks like, as the morning email said it. */
function useMorningBrief() {
  const api = useApi();
  const { storeId } = useStore();
  const store = { params: { path: { store_id: storeId } } };
  const list = useQuery({
    queryKey: ["briefings", storeId],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/stores/{store_id}/briefings", {
          params: { path: { store_id: storeId }, query: { limit: 20 } },
        }),
      ),
  });
  const latest = list.data?.items.find((b) => b.kind === "daily");
  const brief = useQuery({
    queryKey: ["briefing", storeId, latest?.briefing_id],
    enabled: latest !== undefined,
    staleTime: Infinity, // a stored brief does not change
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/stores/{store_id}/briefings/{briefing_id}", {
          params: { path: { ...store.params.path, briefing_id: latest?.briefing_id ?? "" } },
        }),
      ),
  });
  return {
    brief: brief.data,
    pending: list.isPending || (latest !== undefined && brief.isPending),
    none: list.isSuccess && latest === undefined,
    failed: list.isError || brief.isError,
  };
}

/** The morning brief, first in the conversation: the day, the picture, what needs the owner. */
export function Brief() {
  const { brief, pending, none, failed } = useMorningBrief();
  const { timezone } = useStore();
  if (pending) return <p className="h-24 animate-pulse rounded-card bg-subtle" aria-busy="true" />;
  if (failed)
    return <p className="text-body text-ink-muted">The morning brief could not be loaded.</p>;
  if (none || !brief) {
    return (
      <p className="text-body text-ink-muted">
        No morning brief yet: the first one arrives with your next daily summary.
      </p>
    );
  }

  return (
    <article aria-label="Morning brief" className="flex flex-col gap-6">
      <p className="text-center text-caption font-medium tracking-[1.4px] text-ink-muted uppercase">
        {formatWeekday(brief.local_date)}
      </p>
      <header className="flex flex-col gap-3">
        <p className="text-label text-ink-muted">{formatTime(brief.scheduled_at, timezone)}</p>
        <h1 className="text-title font-semibold text-ink">{brief.headline}</h1>
        {brief.narrative && (
          <p className="text-body text-ink-muted">
            <RichText text={brief.narrative} facts={brief.facts} names={brief.names} />
          </p>
        )}
      </header>
      <DocumentSections document={brief} pictureTitle="Your weekly picture" />
    </article>
  );
}
