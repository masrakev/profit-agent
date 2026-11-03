import { DocumentSections } from "./DocumentSections";
import { useMorningBrief } from "./morningBrief";
import { RichText } from "./RichText";
import { formatTime, formatWeekday } from "@/format/dates";
import { useStore } from "@/stores/store";
import { AgentMark } from "@/ui/AgentMark";
import { Skeleton } from "@/ui/Skeleton";

/** The morning brief, first in the conversation: the day, the picture, what needs the owner. */
export function Brief() {
  const { brief, pending, none, failed } = useMorningBrief();
  const { timezone } = useStore();
  if (pending) return <Skeleton rows={3} />;
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
    <article aria-label="Morning brief" className="flex flex-col gap-10">
      <header className="flex flex-col gap-4">
        <p className="flex items-center gap-2 font-mono text-label text-ink-muted">
          <AgentMark size="sm" />
          <span>{formatWeekday(brief.local_date)}</span>
          <span aria-hidden="true" className="h-3 w-px bg-line" />
          <time>{formatTime(brief.scheduled_at, timezone)}</time>
        </p>
        <h1 className="max-w-[24ch] text-title font-semibold text-ink md:text-proof">
          {brief.headline}
        </h1>
        {brief.narrative && (
          <p className="max-w-[65ch] text-body text-ink-muted">
            <RichText text={brief.narrative} facts={brief.facts} names={brief.names} />
          </p>
        )}
      </header>
      <DocumentSections document={brief} pictureTitle="Your weekly picture" />
    </article>
  );
}
