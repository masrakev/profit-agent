import { useQuery } from "@tanstack/react-query";

import { useConversation } from "./context";
import { RichText, type Facts, type Names } from "./RichText";
import { unwrap, type Schemas } from "@/api/client";
import { useApi } from "@/api/context";
import { RangeBar } from "@/charts/RangeBar";
import { estimateOf } from "@/facts/facts";
import { VerifiedSeal } from "@/facts/VerifiedSeal";
import { formatTime, formatWeekday } from "@/format/dates";
import { useStore } from "@/stores/store";
import { Button } from "@/ui/Button";
import { cx } from "@/ui/cx";
import { Icon } from "@/ui/Icon";
import { StatusPill } from "@/ui/StatusPill";

type Briefing = Schemas["BriefingOut"];
type Section = Briefing["sections"][number];
type Item = Section["items"][number];

const FACT = /\{\{F(\d+)\}\}/;

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
  const facts: Facts = brief.facts;
  const names: Names = brief.names;
  const section = (key: string) => brief.sections.find((s) => s.key === key);
  const known = new Set([
    "health",
    "money_at_stake",
    "top_items",
    "pending_decisions",
    "data_notice",
  ]);

  return (
    <article aria-label="Morning brief" className="flex flex-col gap-6">
      <p className="text-center text-caption font-medium tracking-[1.4px] text-ink-muted uppercase">
        {formatWeekday(brief.local_date)}
      </p>
      <header className="flex flex-col gap-3">
        <p className="text-label text-ink-muted">{formatTime(brief.created_at, timezone)}</p>
        <h1 className="text-title font-semibold text-ink">{brief.headline}</h1>
        {brief.narrative && (
          <p className="text-body text-ink-muted">
            <RichText text={brief.narrative} facts={facts} names={names} />
          </p>
        )}
      </header>
      <Picture
        health={section("health")}
        stake={section("money_at_stake")}
        notice={section("data_notice")}
        facts={facts}
        names={names}
      />
      {section("top_items")?.items.map((item, index) => (
        <Attention key={index} item={item} facts={facts} names={names} />
      ))}
      <Pending section={section("pending_decisions")} facts={facts} names={names} />
      {brief.sections
        .filter((s) => !known.has(s.key))
        .map((s) => (
          <Generic key={s.key} section={s} facts={facts} names={names} />
        ))}
    </article>
  );
}

interface Parts {
  facts: Facts;
  names: Names;
}

function firstFact(text: string, facts: Facts) {
  const id = FACT.exec(text)?.[1];
  return id ? facts[id] : undefined;
}

/** "Your weekly picture": the health line, the money at stake with its range, the data notice. */
function Picture({
  health,
  stake,
  notice,
  facts,
  names,
}: Parts & { health?: Section; stake?: Section; notice?: Section }) {
  if (!health && !stake) return null;
  const stakeText = stake?.items[0]?.text;
  const stakeFact = stakeText ? firstFact(stakeText, facts) : undefined;
  const sealed = (health?.items[0] && firstFact(health.items[0].text, facts)) ?? stakeFact;
  return (
    <section
      aria-label="Your weekly picture"
      className="flex flex-col gap-4 rounded-card border border-line bg-surface p-6 shadow-float"
    >
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-small font-semibold text-ink">Your weekly picture</h2>
        {sealed && <VerifiedSeal fact={sealed} />}
      </div>
      {health?.items.map((item, index) => (
        <p key={index} className="text-body text-ink">
          <RichText text={item.text} facts={facts} names={names} />
        </p>
      ))}
      {stakeText && (
        <div className="flex flex-col gap-3">
          <p className="text-body text-ink">
            <span className="text-ink-muted">Money at stake: </span>
            <RichText text={stakeText} facts={facts} names={names} />
          </p>
          {stakeFact && estimateOf(stakeFact) && (
            <RangeBar fact={stakeFact} title="Money at stake" />
          )}
        </div>
      )}
      {notice?.items.map((item, index) => (
        <p key={index} className="self-start">
          <StatusPill tone="warning">{item.text}</StatusPill>
        </p>
      ))}
    </section>
  );
}

/** "Worth your attention": one problem, its options one click away, its evidence another. */
function Attention({ item, facts, names }: Parts & { item: Item }) {
  const { openDecision, openInvestigation } = useConversation();
  const critical = item.level === "critical";
  const decision = item.decision_id;
  const incident = item.incident_id;
  return (
    <section
      aria-label="Worth your attention"
      className={cx(
        "flex flex-col gap-4 rounded-card border border-line bg-surface p-6 shadow-float",
        critical && "border-l-4 border-l-danger",
      )}
    >
      <p className="flex items-center gap-2 text-label text-ink-muted">
        <Icon name="flag" size={16} />
        Worth your attention
        {item.level && <span className="sr-only">: {item.level}</span>}
      </p>
      <p className="text-body text-ink">
        <RichText text={item.text} facts={facts} names={names} />
      </p>
      <div className="flex flex-wrap items-center gap-2.5">
        {decision && (
          <Button
            onClick={() => {
              openDecision(decision);
            }}
          >
            See options
          </Button>
        )}
        {incident && (
          <Button
            variant="secondary"
            onClick={() => {
              openInvestigation(incident);
            }}
          >
            What I checked
          </Button>
        )}
        <span className="ml-auto text-label text-ink-muted">No changes made</span>
      </div>
    </section>
  );
}

function Pending({ section, facts, names }: Parts & { section?: Section }) {
  const { openDecision } = useConversation();
  if (!section || section.items.length === 0) return null;
  return (
    <section aria-label={section.title} className="flex flex-col gap-3">
      <h2 className="text-small font-semibold text-ink">{section.title}</h2>
      <ul className="flex flex-col gap-2">
        {section.items.map((item, index) => {
          const decision = item.decision_id;
          return (
            <li
              key={index}
              className="flex items-center justify-between gap-4 rounded-box border border-line bg-surface px-4 py-3 text-small text-ink"
            >
              <span>
                <RichText text={item.text} facts={facts} names={names} />
              </span>
              {decision && (
                <Button
                  variant="ghost"
                  className="h-9 px-3"
                  onClick={() => {
                    openDecision(decision);
                  }}
                >
                  Review
                </Button>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function Generic({ section, facts, names }: Parts & { section: Section }) {
  return (
    <section aria-label={section.title} className="flex flex-col gap-2">
      <h2 className="text-small font-semibold text-ink">{section.title}</h2>
      {section.items.length === 0 && section.empty && (
        <p className="text-small text-ink-muted">{section.empty}</p>
      )}
      {section.items.map((item, index) => (
        <p key={index} className="text-small text-ink">
          <RichText text={item.text} facts={facts} names={names} />
        </p>
      ))}
    </section>
  );
}
