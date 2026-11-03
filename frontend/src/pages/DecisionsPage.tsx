import { useState, type KeyboardEvent } from "react";
import { Link, Navigate, useNavigate, useParams, useSearchParams } from "react-router";

import type { Schemas } from "@/api/client";
import { DecisionDetail } from "@/decisions/DecisionDetail";
import { rowFacts, useFacts } from "@/decisions/facts";
import { SOURCES, statusOf } from "@/decisions/status";
import { useDecisions } from "@/decisions/useDecisions";
import { localDay } from "@/format/dates";
import { useStore } from "@/stores/store";
import { cx } from "@/ui/cx";
import { EmptyState } from "@/ui/EmptyState";
import { Icon } from "@/ui/Icon";
import { Skeleton } from "@/ui/Skeleton";

type Decision = Schemas["DecisionView"];

/** The inbox's folders: the owner's first. */
const FOLDERS: { name: string; statuses: string[] }[] = [
  { name: "To decide", statuses: ["proposed"] },
  { name: "In progress", statuses: ["approved", "executing"] },
  { name: "Done", statuses: ["executed", "measured", "failed"] },
  { name: "Closed", statuses: ["rejected", "expired", "superseded"] },
];

const DOTS = {
  good: "bg-good",
  warning: "bg-warning",
  critical: "bg-danger",
  info: "bg-accent-mark",
  neutral: "bg-ink-muted",
} as const;

const folderOf = (d: Decision) =>
  FOLDERS.find((f) => f.statuses.includes(d.status))?.name ?? "Closed";

/**
 * Decisions as an inbox: the list on the left, one decision in full on the right (on a phone,
 * the list, then the decision on its own page). Each decision has its address, so "See options"
 * anywhere, a link or a notification opens it directly.
 */
export function DecisionsPage() {
  const { decisionId } = useParams();
  const [params] = useSearchParams();
  const legacy = params.get("open");
  const navigate = useNavigate();
  const { timezone } = useStore();
  const decisions = useDecisions();
  const items = decisions.data?.items ?? [];
  const current = items.find((d) => d.decision_id === decisionId);
  const [picked, setPicked] = useState<string | null>(null);
  const facts = useFacts(items.flatMap((d) => Object.values(rowFacts(d))));

  if (legacy) return <Navigate to={`/decisions/${encodeURIComponent(legacy)}`} replace />;

  const fallback = items.some((d) => d.status === "proposed") ? "To decide" : "Done";
  const folder = picked ?? (current ? folderOf(current) : fallback);
  const shown = items.filter((d) => folderOf(d) === folder);

  // Up and down move through the list, as in a mail client.
  const onKey = (event: KeyboardEvent<HTMLAnchorElement>) => {
    if (!["ArrowDown", "ArrowUp", "j", "k"].includes(event.key)) return;
    const list = event.currentTarget.closest("ul");
    const links = [...(list?.querySelectorAll<HTMLAnchorElement>("a[data-row]") ?? [])];
    const at = links.findIndex((a) => a === document.activeElement);
    const step = event.key === "ArrowDown" || event.key === "j" ? 1 : -1;
    const next = links.at(Math.min(Math.max(at + step, 0), links.length - 1));
    if (!next) return;
    event.preventDefault();
    next.focus();
    void navigate(next.getAttribute("href") ?? "/decisions");
  };

  return (
    <section aria-labelledby="decisions-title" className="flex flex-col gap-8">
      <header className={cx("flex flex-col gap-2", decisionId && "max-lg:hidden")}>
        <h1 id="decisions-title" className="text-title font-semibold text-ink">
          Decisions
        </h1>
        <p className="text-body text-ink-muted">
          What I proposed, what you answered, and what came of it.
        </p>
      </header>
      {decisions.isPending && <Skeleton rows={4} />}
      {decisions.isError && (
        <p className="text-body text-ink-muted">The decisions could not be loaded.</p>
      )}
      {decisions.data && items.length === 0 && (
        <EmptyState title="No decision yet.">
          When I find something worth changing, I simulate it first and ask you here, with what it
          should earn and what could go wrong.
        </EmptyState>
      )}
      {items.length > 0 && (
        <div className="grid gap-8 lg:grid-cols-[320px_minmax(0,1fr)] lg:gap-12">
          <nav
            aria-label="Decisions list"
            className={cx(
              "flex flex-col gap-4 lg:sticky lg:top-6 lg:max-h-[calc(100dvh-3rem)] lg:self-start lg:overflow-y-auto",
              decisionId && "max-lg:hidden",
            )}
          >
            <div role="group" aria-label="Show" className="flex flex-wrap gap-1.5">
              {FOLDERS.map((f) => {
                const has = items.some((d) => folderOf(d) === f.name);
                return (
                  <button
                    key={f.name}
                    type="button"
                    aria-pressed={folder === f.name}
                    onClick={() => {
                      setPicked(f.name);
                    }}
                    className={cx(
                      "inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-full px-3 text-small transition-colors duration-150",
                      folder === f.name
                        ? "bg-subtle font-medium text-ink"
                        : "text-ink-muted hover:text-ink",
                    )}
                  >
                    {f.name}
                    {f.name === "To decide" && has && (
                      <span aria-hidden="true" className="size-1.5 rounded-full bg-warning" />
                    )}
                  </button>
                );
              })}
            </div>
            {shown.length === 0 ? (
              <p className="py-6 text-small text-ink-muted">Nothing here.</p>
            ) : (
              <ul aria-label={folder} className="flex flex-col border-t border-line" data-stagger>
                {shown.map((d) => {
                  const chosen = d.options.find((o) => o.option_id === d.approved_option_id);
                  const status = statusOf(d.status);
                  const { expected, measured } = rowFacts(d);
                  const amount = facts.get(measured ?? expected ?? -1);
                  const open = d.decision_id === decisionId;
                  return (
                    <li key={d.decision_id} className="border-b border-line">
                      <Link
                        to={`/decisions/${d.decision_id}`}
                        data-row
                        onKeyDown={onKey}
                        aria-current={open ? "page" : undefined}
                        className={cx(
                          "-mx-3 flex flex-col gap-1.5 rounded-md px-3 py-3.5 transition-colors duration-150",
                          open ? "bg-subtle" : "hover:bg-subtle/60",
                        )}
                      >
                        <span className="flex items-start justify-between gap-3">
                          <span
                            className={cx(
                              "text-small text-ink",
                              d.status === "proposed" && "font-semibold",
                              d.status === "superseded" && "text-ink-muted line-through",
                            )}
                          >
                            {chosen?.label ?? d.label}
                          </span>
                          {amount && (
                            <span className="shrink-0 text-label text-ink tabular-nums">
                              {amount.display}
                            </span>
                          )}
                        </span>
                        <span className="flex flex-wrap items-center gap-x-2 text-label text-ink-muted">
                          <span
                            aria-hidden="true"
                            className={cx("size-1.5 rounded-full", DOTS[status.tone])}
                          />
                          <span>{status.text}</span>
                          <span aria-hidden="true">·</span>
                          <span>{SOURCES[d.source] ?? d.source}</span>
                          <time className="font-mono">
                            {localDay(d.created_at, timezone).label}
                          </time>
                        </span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            )}
          </nav>
          <div className={cx("min-w-0", !decisionId && "max-lg:hidden")}>
            {decisionId ? (
              <div className="flex flex-col gap-6">
                <Link
                  to="/decisions"
                  className="inline-flex items-center gap-1.5 self-start rounded-md text-small text-ink-muted hover:text-ink lg:hidden"
                >
                  <Icon name="chevron-up" size={16} className="-rotate-90" />
                  All decisions
                </Link>
                <DecisionDetail key={decisionId} decisionId={decisionId} />
              </div>
            ) : (
              <EmptyState title="Pick a decision.">
                Each one reads top to bottom: why I proposed it, what you decided, what happened and
                what it earned.
              </EmptyState>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
