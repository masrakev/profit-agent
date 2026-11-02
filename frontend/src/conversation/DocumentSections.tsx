import { useOpenInChat } from "./open";
import { RichText, type Facts, type Names } from "./RichText";
import type { Schemas } from "@/api/client";
import { RangeBar } from "@/charts/RangeBar";
import { estimateOf } from "@/facts/facts";
import { VerifiedSeal } from "@/facts/VerifiedSeal";
import { Button } from "@/ui/Button";
import { cx } from "@/ui/cx";
import { Icon } from "@/ui/Icon";
import { StatusPill } from "@/ui/StatusPill";

type Document = Schemas["DocumentOut"];
type Section = Document["sections"][number];
type Item = Section["items"][number];

const FACT = /\{\{F(\d+)\}\}/;
const KNOWN = new Set([
  "health",
  "money_at_stake",
  "top_items",
  "pending_decisions",
  "data_notice",
]);

/**
 * A document assembled by code from facts (a briefing, today's overview): the picture, what needs
 * the owner, the pending decisions, then any other section as it comes.
 */
export function DocumentSections({
  document,
  pictureTitle,
}: {
  document: Document;
  pictureTitle: string;
}) {
  const { facts, names } = document;
  const section = (key: string) => document.sections.find((s) => s.key === key);
  return (
    <>
      <Picture
        title={pictureTitle}
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
      {document.sections
        .filter((s) => !KNOWN.has(s.key))
        .map((s) => (
          <Generic key={s.key} section={s} facts={facts} names={names} />
        ))}
    </>
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

/** The picture: the health line, the money at stake with its range, the data notice. */
function Picture({
  title,
  health,
  stake,
  notice,
  facts,
  names,
}: Parts & { title: string; health?: Section; stake?: Section; notice?: Section }) {
  if (!health && !stake) return null;
  const stakeText = stake?.items[0]?.text;
  const stakeFact = stakeText ? firstFact(stakeText, facts) : undefined;
  const sealed = (health?.items[0] && firstFact(health.items[0].text, facts)) ?? stakeFact;
  return (
    <section
      aria-label={title}
      className="flex flex-col gap-4 rounded-card border border-line bg-surface p-6 shadow-float"
    >
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-small font-semibold text-ink">{title}</h2>
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
  const open = useOpenInChat();
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
              open.decision(decision);
            }}
          >
            See options
          </Button>
        )}
        {incident && (
          <Button
            variant="secondary"
            onClick={() => {
              open.investigation(incident);
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
  const open = useOpenInChat();
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
                    open.decision(decision);
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
