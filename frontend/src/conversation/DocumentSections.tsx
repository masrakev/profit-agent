import { useOpen } from "./open";
import { RichText, type Facts, type Names } from "./RichText";
import type { Schemas } from "@/api/client";
import { RangeBar } from "@/charts/RangeBar";
import { estimateOf } from "@/facts/facts";
import { VerifiedSeal } from "@/facts/VerifiedSeal";
import { Button } from "@/ui/Button";
import { cx } from "@/ui/cx";

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
 * A document assembled by code from facts (a briefing, today's overview), read top to bottom like
 * an editorial brief: what needs the owner first, then the picture and the money at stake, then
 * the pending decisions as rows, then any other section as it comes. No cards: sections and
 * hairlines carry the order.
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
  const attention = section("top_items")?.items ?? [];
  return (
    <div className="flex flex-col gap-10">
      {attention.length > 0 && (
        <ul className="flex flex-col border-t border-line" data-stagger>
          {attention.map((item, index) => (
            <Attention key={index} item={item} facts={facts} names={names} />
          ))}
        </ul>
      )}
      <Picture
        title={pictureTitle}
        health={section("health")}
        stake={section("money_at_stake")}
        notice={section("data_notice")}
        facts={facts}
        names={names}
      />
      <Pending section={section("pending_decisions")} facts={facts} names={names} />
      {document.sections
        .filter((s) => !KNOWN.has(s.key))
        .map((s) => (
          <Generic key={s.key} section={s} facts={facts} names={names} />
        ))}
    </div>
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

/** The picture: the health line, the money at stake (its range read once), the data notice. */
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
    <section aria-label={title} className="flex flex-col gap-4">
      <div className="flex items-baseline justify-between gap-3 border-b border-line pb-2.5">
        <h2 className="text-small font-medium text-ink-muted">{title}</h2>
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
            <RangeBar fact={stakeFact} title="Money at stake" range={false} />
          )}
        </div>
      )}
      {notice?.items.map((item, index) => (
        <p key={index} className="flex items-start gap-2 text-small text-ink-muted">
          <span aria-hidden="true" className="mt-[7px] size-1.5 shrink-0 rounded-full bg-warning" />
          {item.text}
        </p>
      ))}
    </section>
  );
}

const LEVELS: Record<string, { dot: string; word: string }> = {
  critical: { dot: "bg-danger", word: "Critical" },
  warning: { dot: "bg-warning", word: "Worth watching" },
};

/** One problem worth the owner's attention, as a row: its options and its evidence a click away. */
function Attention({ item, facts, names }: Parts & { item: Item }) {
  const open = useOpen();
  const decision = item.decision_id;
  const incident = item.incident_id;
  const level = item.level ? LEVELS[item.level] : undefined;
  return (
    <li>
      <section
        aria-label="Worth your attention"
        className="flex flex-col gap-3 border-b border-line py-5"
      >
        <p className="flex items-center gap-2 text-label text-ink-muted">
          <span
            aria-hidden="true"
            className={cx("size-1.5 rounded-full", level?.dot ?? "bg-ink-muted")}
          />
          {level?.word ?? "Worth your attention"}
          <span className="sr-only">: {item.level ?? "info"}</span>
        </p>
        <p className="text-body text-ink">
          <RichText text={item.text} facts={facts} names={names} />
        </p>
        <div className="flex flex-wrap items-center gap-2.5">
          {decision && (
            <Button
              className="h-9 px-4 text-small"
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
              className="h-9 px-4 text-small"
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
    </li>
  );
}

function Pending({ section, facts, names }: Parts & { section?: Section }) {
  const open = useOpen();
  if (!section || section.items.length === 0) return null;
  return (
    <section aria-label={section.title} className="flex flex-col">
      <h2 className="border-b border-line pb-2.5 text-small font-medium text-ink-muted">
        {section.title}
      </h2>
      <ul className="flex flex-col" data-stagger>
        {section.items.map((item, index) => {
          const decision = item.decision_id;
          return (
            <li
              key={index}
              className="flex items-center justify-between gap-4 border-b border-line py-3.5 text-body text-ink"
            >
              <span className="min-w-0">
                <RichText text={item.text} facts={facts} names={names} />
              </span>
              {decision && (
                <Button
                  variant="secondary"
                  className="h-9 shrink-0 px-4 text-small"
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
    <section aria-label={section.title} className="flex flex-col gap-3">
      <h2 className="border-b border-line pb-2.5 text-small font-medium text-ink-muted">
        {section.title}
      </h2>
      {section.items.length === 0 && section.empty && (
        <p className="text-small text-ink-muted">{section.empty}</p>
      )}
      {section.items.map((item, index) => (
        <p key={index} className="text-body text-ink">
          <RichText text={item.text} facts={facts} names={names} />
        </p>
      ))}
    </section>
  );
}
