import { useId, useState } from "react";

import type { AnswerStatus, AgentStep, AskAnswer } from "./model";
import { RichText } from "./RichText";
import { modelName } from "./models";
import { Working } from "./Working";
import { FactValue } from "@/facts/FactValue";
import { VerifiedSeal } from "@/facts/VerifiedSeal";
import { StatusPill } from "@/ui/StatusPill";

const FLAGS: Record<string, string> = {
  data_quality: "Data issue: check the data before acting",
  platform_attribution_caveat: "Sales credited by the ad platform, not checked against orders",
  low_evidence: "Little evidence",
  no_material_issue: "Nothing material",
  out_of_scope: "Outside what your data can answer",
  abstain_insufficient_evidence: "Not enough evidence to answer",
};

interface AnswerMessageProps {
  status: AnswerStatus;
  steps: AgentStep[];
  result: AskAnswer | null;
  problem: string | null;
}

/** The agent's reply: its work as it streams, then the answer, every number with its proof. */
export function AnswerMessage({ status, steps, result, problem }: AnswerMessageProps) {
  const names = result?.names ?? {};
  return (
    <div className="flex flex-col gap-5">
      {(status === "working" || steps.length > 0) && (
        <Working steps={steps} names={names} live={status === "working"} />
      )}
      {status === "answered" && result && <Answer result={result} />}
      {status === "no_speech" && (
        <p className="text-body text-ink-muted">
          No speech was heard in the recording: nothing was asked.
        </p>
      )}
      {status === "failed" && (
        <p role="alert" className="text-body text-danger-ink">
          {problem}
        </p>
      )}
    </div>
  );
}

/** Evidence rows shown before "Show all evidence". */
const FIRST_EVIDENCE = 4;

function Answer({ result }: { result: AskAnswer }) {
  const [more, setMore] = useState(false);
  const [allEvidence, setAllEvidence] = useState(false);
  const detailsId = useId();
  const { answer, facts, names } = result;
  const evidence = answer.evidence.flatMap((id) => {
    const fact = facts[String(id)];
    return fact ? [fact] : [];
  });
  const sealed = evidence[0];
  const answeredBy = modelName(result.model);
  const deeper =
    Boolean(answer.reasoning) ||
    answer.alternatives.length > 0 ||
    Boolean(answer.would_change_my_mind);

  return (
    <article aria-label="Answer" className="flex gap-3">
      <div className="flex min-w-0 flex-1 flex-col gap-5">
        <p className="max-w-[65ch] text-body text-ink">
          <RichText text={answer.answer} facts={facts} names={names} />
        </p>
        {answer.recommendation && (
          <p className="max-w-[65ch] text-body text-ink">
            <span className="font-semibold">Next step: </span>
            <RichText text={answer.recommendation} facts={facts} names={names} />
          </p>
        )}
        {evidence.length > 0 && (
          <section aria-label="Evidence" className="flex flex-col">
            <div className="flex items-baseline justify-between gap-3 border-b border-line pb-2">
              <h3 className="text-small font-medium text-ink-muted">Evidence</h3>
              {sealed && <VerifiedSeal fact={sealed} />}
            </div>
            <ul className="flex flex-col" data-stagger>
              {(allEvidence ? evidence : evidence.slice(0, FIRST_EVIDENCE)).map((fact) => (
                <li
                  key={fact.fact_id}
                  className="flex items-baseline justify-between gap-4 border-b border-line py-2.5 text-small"
                >
                  <span className="min-w-0 text-ink-muted">{fact.name}</span>
                  <FactValue fact={fact} title={fact.name} className="shrink-0 text-ink" />
                </li>
              ))}
            </ul>
            {evidence.length > FIRST_EVIDENCE && (
              <button
                type="button"
                aria-expanded={allEvidence}
                onClick={() => {
                  setAllEvidence((was) => !was);
                }}
                className="mt-2.5 cursor-pointer self-start rounded-md text-small text-ink-muted hover:text-ink"
              >
                {allEvidence ? "Show less evidence" : "Show all evidence"}
              </button>
            )}
          </section>
        )}
        {answer.uncertainty && (
          <p className="max-w-[65ch] text-small text-ink-muted">
            <span className="font-semibold">Still uncertain: </span>
            <RichText text={answer.uncertainty} facts={facts} names={names} />
          </p>
        )}
        {answer.flags.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {answer.flags.map((flag) => (
              <StatusPill key={flag} tone={flag === "data_quality" ? "warning" : "neutral"}>
                {FLAGS[flag] ?? flag}
              </StatusPill>
            ))}
          </div>
        )}
        {deeper && (
          <div className="flex flex-col gap-3">
            <button
              type="button"
              aria-expanded={more}
              aria-controls={detailsId}
              onClick={() => {
                setMore((was) => !was);
              }}
              className="cursor-pointer self-start rounded-md text-small font-medium text-ink underline decoration-line underline-offset-4 hover:decoration-ink-muted"
            >
              {more ? "Hide how I got there" : "How I got there"}
            </button>
            <div
              id={detailsId}
              hidden={!more}
              className="flex-col gap-3 text-small text-ink [&:not([hidden])]:flex"
            >
              {answer.reasoning && (
                <p>
                  <RichText text={answer.reasoning} facts={facts} names={names} />
                </p>
              )}
              {answer.alternatives.length > 0 && (
                <div className="flex flex-col gap-1">
                  <p className="font-semibold">Also considered</p>
                  <ul className="flex list-disc flex-col gap-1 pl-5">
                    {answer.alternatives.map((alternative, index) => (
                      <li key={index}>
                        <RichText text={alternative} facts={facts} names={names} />
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {answer.would_change_my_mind && (
                <p className="text-ink-muted">
                  <span className="font-semibold">What would change this: </span>
                  <RichText text={answer.would_change_my_mind} facts={facts} names={names} />
                </p>
              )}
            </div>
          </div>
        )}
        {answeredBy && <p className="text-label text-ink-muted">Answered with {answeredBy}</p>}
      </div>
    </article>
  );
}
