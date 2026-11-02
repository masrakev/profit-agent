import { useInfiniteQuery } from "@tanstack/react-query";

import type { Fact, FactDetail } from "./facts";
import { unwrap } from "@/api/client";
import { useApi } from "@/api/context";
import { formatDay } from "@/format/dates";
import { counted, humanize } from "@/format/words";
import { Button } from "@/ui/Button";

type Source = FactDetail["sources"][number];

const PAGE = 10;

/**
 * A source of a base fact: where its rows come from and how recent that data is, then the rows
 * themselves by date with their exact amounts, a page at a time, and the fact as their total.
 */
export function SourceRows({
  storeId,
  fact,
  source,
}: {
  storeId: string;
  fact: Fact;
  source: Source;
}) {
  const api = useApi();
  const rows = useInfiniteQuery({
    queryKey: ["fact-rows", storeId, fact.fact_id, source.table],
    initialPageParam: null as string | null,
    staleTime: Infinity, // a fact's rows never change
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/stores/{store_id}/facts/{fact_id}/rows", {
          params: {
            path: { store_id: storeId, fact_id: fact.fact_id },
            query: { table: source.table, limit: PAGE, cursor: pageParam },
          },
        }),
      ),
    getNextPageParam: (page) => page.next_cursor ?? null,
  });
  const items = rows.data?.pages.flatMap((page) => page.items) ?? [];
  const upTo = source.data_up_to ? formatDay(source.data_up_to) : null;

  return (
    <div className="flex flex-col gap-3">
      <p className="flex items-start justify-between gap-4 text-label leading-[1.45] text-ink-muted">
        <span>{source.source ?? humanize(source.table)}</span>
        <span>{counted(source.count, "row")}</span>
      </p>
      {rows.isError && <p className="text-small text-ink-muted">The rows could not be loaded.</p>}
      {items.length > 0 && (
        <ul className="flex flex-col">
          {items.map((row) => (
            <li
              key={row.id}
              className="flex items-baseline justify-between gap-4 border-b border-line py-3 text-ink"
            >
              <span className="flex min-w-0 flex-col text-small">
                <span>{row.day ? formatDay(row.day) : "—"}</span>
                {row.label && <span className="truncate text-ink-muted">{row.label}</span>}
              </span>
              <span className="text-body">{row.amount.formatted}</span>
            </li>
          ))}
        </ul>
      )}
      {rows.hasNextPage && (
        <Button
          variant="ghost"
          className="self-start px-0 hover:bg-transparent hover:underline"
          disabled={rows.isFetchingNextPage}
          onClick={() => {
            void rows.fetchNextPage();
          }}
        >
          {rows.isFetchingNextPage ? "Loading…" : "Show more rows"}
        </Button>
      )}
      {items.length > 0 && !rows.hasNextPage && (
        <p className="flex items-baseline justify-between gap-4 text-body font-semibold text-ink">
          <span>Total</span>
          <span>{fact.formatted}</span>
        </p>
      )}
      {upTo && <p className="text-label leading-[1.45] text-ink-muted">Data up to {upTo}</p>}
    </div>
  );
}
