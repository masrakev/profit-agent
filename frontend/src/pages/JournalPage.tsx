import { useQueries, useQuery } from "@tanstack/react-query";

import { unwrap, type Schemas } from "@/api/client";
import { useApi } from "@/api/context";
import { useOpenInChat } from "@/conversation/open";
import { statusOf } from "@/decisions/status";
import { FactValue } from "@/facts/FactValue";
import { factKey, type Fact } from "@/facts/facts";
import { formatTime, localDay } from "@/format/dates";
import { useStore } from "@/stores/store";
import { Icon } from "@/ui/Icon";
import type { IconName } from "@/ui/icons";
import { StatusPill } from "@/ui/StatusPill";

type Entry = Schemas["JournalEntry"];
type Decision = Schemas["DecisionView"];

const PAGES = 5; // the API keeps the latest 500 entries: at most this many pages of 200

const ALERTS: Record<string, string> = {
  critical: "A critical problem was found",
  high: "An important problem was found",
  medium: "A problem was found",
  low: "A small problem was found",
  watchlist: "Something to watch was noted",
  data_quality: "A problem with the data was found",
};
const CATEGORIES: Record<string, string> = {
  profitability: "in profitability",
  data_quality: "in the data",
  operations: "in operations",
};
const CHANNELS: Record<string, string> = {
  api: "in the app",
  web: "in the app",
  email: "by email",
  whatsapp: "on WhatsApp",
};
const ICONS: Record<string, IconName> = {
  incident: "flag",
  decision: "message-circle",
  approval: "circle-check",
  action: "file-check",
  outcome: "flask-conical",
};

/**
 * The journal: everything that happened in the store's agent, newest first, day by day: problems
 * found, decisions proposed, the owner's answers, what was carried out and what it was measured
 * to do. Each line names what it is about; measured effects open their proof.
 */
export function JournalPage() {
  const api = useApi();
  const { storeId } = useStore();
  const path = { store_id: storeId };

  const journal = useQuery({
    queryKey: ["journal", storeId, "all"],
    queryFn: async () => {
      const entries: Entry[] = [];
      let cursor: string | null = null;
      for (let page = 0; page < PAGES; page += 1) {
        const query: { limit: number; cursor?: string } = { limit: 200 };
        if (cursor) query.cursor = cursor;
        const found = await unwrap(
          api.GET("/api/v1/stores/{store_id}/journal", { params: { path, query } }),
        );
        entries.push(...found.items);
        cursor = found.next_cursor ?? null;
        if (!cursor) break;
      }
      return entries; // newest first, as the API lists them
    },
  });
  const decisions = useQuery({
    queryKey: ["decisions", storeId],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/stores/{store_id}/decisions", {
          params: { path, query: { limit: 200 } },
        }),
      ),
  });
  const byId = new Map((decisions.data?.items ?? []).map((d) => [d.decision_id, d]));

  const effects = (journal.data ?? []).flatMap((e) => {
    const id = (e.summary as { effect_fact_id?: unknown }).effect_fact_id;
    return e.kind === "outcome" && typeof id === "number" ? [id] : [];
  });
  const factQueries = useQueries({
    queries: effects.map((factId) => ({
      queryKey: factKey(storeId, factId),
      staleTime: Infinity,
      queryFn: () =>
        unwrap(
          api.GET("/api/v1/stores/{store_id}/facts/{fact_id}", {
            params: { path: { ...path, fact_id: factId } },
          }),
        ),
    })),
  });
  const facts = new Map<number, Fact>(
    factQueries.flatMap((q) => (q.data ? [[q.data.fact.fact_id, q.data.fact] as const] : [])),
  );

  return (
    <section aria-labelledby="journal-title" className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <h1 id="journal-title" className="text-title font-semibold text-ink">
          Journal
        </h1>
        <p className="text-body text-ink-muted">
          Everything that happened, newest first: what I found, what you decided, what changed.
        </p>
      </header>
      {journal.isPending && (
        <p className="h-40 animate-pulse rounded-card bg-subtle" aria-busy="true" />
      )}
      {journal.isError && (
        <p className="text-body text-ink-muted">The journal could not be loaded.</p>
      )}
      {journal.data?.length === 0 && (
        <p className="text-body text-ink-muted">Nothing has happened yet.</p>
      )}
      {journal.data && <Days entries={journal.data} decisions={byId} facts={facts} />}
    </section>
  );
}

function Days({
  entries,
  decisions,
  facts,
}: {
  entries: Entry[];
  decisions: Map<string, Decision>;
  facts: Map<number, Fact>;
}) {
  const { timezone } = useStore();
  const days: { key: string; label: string; entries: Entry[] }[] = [];
  for (const entry of entries) {
    const day = localDay(entry.at, timezone);
    const last = days.at(-1);
    if (last?.key === day.key) last.entries.push(entry);
    else days.push({ ...day, entries: [entry] });
  }
  return (
    <>
      {days.map((day) => (
        <section key={day.key} aria-label={day.label} className="flex flex-col gap-3">
          <h2 className="text-caption font-medium tracking-[1.4px] text-ink-muted uppercase">
            {day.label}
          </h2>
          <ol className="flex flex-col gap-2">
            {day.entries.map((entry) => (
              <JournalLine
                key={`${entry.kind}:${entry.id}`}
                entry={entry}
                decisions={decisions}
                facts={facts}
              />
            ))}
          </ol>
        </section>
      ))}
    </>
  );
}

interface Summary {
  alert?: unknown;
  category?: unknown;
  decision_id?: unknown;
  status?: unknown;
  verdict?: unknown;
  option_id?: unknown;
  channel?: unknown;
  provider?: unknown;
  after?: { status?: unknown } | null;
  error?: unknown;
  rollback_of?: unknown;
  effect_fact_id?: unknown;
}

const text = (value: unknown): string | null => (typeof value === "string" ? value : null);

function JournalLine({
  entry,
  decisions,
  facts,
}: {
  entry: Entry;
  decisions: Map<string, Decision>;
  facts: Map<number, Fact>;
}) {
  const { timezone } = useStore();
  const open = useOpenInChat();
  const s = entry.summary as Summary;
  const decisionId = text(s.decision_id) ?? (entry.kind === "decision" ? entry.id : null);
  const decision = decisionId ? decisions.get(decisionId) : undefined;
  const option = decision?.options.find(
    (o) => o.option_id === (text(s.option_id) ?? decision.approved_option_id),
  );
  const what = option?.label ?? decision?.label ?? "a decision";
  const platform = s.provider === "meta" ? "Meta Ads" : "The ad platform";
  const effect = typeof s.effect_fact_id === "number" ? facts.get(s.effect_fact_id) : undefined;

  let line: string;
  let detail: string | null = null;
  let pill: { tone: "good" | "warning" | "critical" | "info" | "neutral"; text: string } | null =
    null;
  switch (entry.kind) {
    case "incident":
      line = `${ALERTS[text(s.alert) ?? ""] ?? "A problem was found"} ${
        CATEGORIES[text(s.category) ?? ""] ?? ""
      }`.trim();
      break;
    case "decision":
      line = decision?.source === "owner" ? `You asked: ${what}` : `I proposed: ${what}`;
      pill = decision ? statusOf(decision.status) : null;
      break;
    case "approval": {
      const how = CHANNELS[text(s.channel) ?? ""] ?? "";
      line =
        s.verdict === "approved"
          ? `You approved ${how}: ${what}`.replace(" :", ":")
          : `You said not now ${how}: ${decision?.label ?? what}`.replace(" :", ":");
      break;
    }
    case "action": {
      const state = text(s.after?.status);
      if (s.status === "failed") {
        line = `Could not be carried out: ${what}`;
        detail = text(s.error);
      } else {
        line = s.rollback_of ? `Undone: ${what}` : `Carried out: ${what}`;
        detail = state ? `${platform} reports the campaign ${state.toLowerCase()}.` : null;
      }
      break;
    }
    case "outcome":
      line = s.status === "measured" ? `Measured: ${what}` : `Could not be measured: ${what}`;
      break;
    default:
      line = entry.kind;
  }

  return (
    <li className="flex items-start gap-3 rounded-box border border-line bg-surface px-4 py-3">
      <Icon
        name={ICONS[entry.kind] ?? "circle-check"}
        size={16}
        className="mt-1 shrink-0 text-accent-ink"
      />
      <div className="flex flex-1 flex-col gap-1">
        <p className="text-small text-ink">{line}</p>
        {detail && <p className="text-label text-ink-muted">{detail}</p>}
        {effect && (
          <p className="text-label text-ink-muted">
            Its measured effect on net profit:{" "}
            <FactValue fact={effect} title="Measured effect" className="text-ink" />
          </p>
        )}
        {entry.kind === "incident" && (
          <button
            type="button"
            onClick={() => {
              open.investigation(entry.id);
            }}
            className="cursor-pointer self-start text-label font-semibold text-accent-ink hover:underline"
          >
            What I checked
          </button>
        )}
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1">
        <time dateTime={entry.at} className="text-label text-ink-muted">
          {formatTime(entry.at, timezone)}
        </time>
        {pill && <StatusPill tone={pill.tone}>{pill.text}</StatusPill>}
      </div>
    </li>
  );
}
