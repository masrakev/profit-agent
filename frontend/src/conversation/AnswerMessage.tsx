import { useId, useState } from "react";

import type { AnswerStatus, AgentStep, AskAnswer } from "./model";
import { RichText } from "./RichText";
import { Working } from "./Working";
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
    <div className="flex flex-col gap-3">
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

function Answer({ result }: { result: AskAnswer }) {
  const [more, setMore] = useState(false);
  const detailsId = useId();
  const { answer, facts, names } = result;
  const sealed = answer.evidence.map((id) => facts[String(id)]).find((fact) => fact);
  const deeper =
    Boolean(answer.reasoning) ||
    answer.alternatives.length > 0 ||
    Boolean(answer.would_change_my_mind);

  return (
    <article
      aria-label="Answer"
      className="flex flex-col gap-4 rounded-card border border-line bg-surface p-6 shadow-float"
    >
      <div className="flex items-start justify-between gap-4">
        <p className="text-body text-ink">
          <RichText text={answer.answer} facts={facts} names={names} />
        </p>
        {sealed && <VerifiedSeal fact={sealed} />}
      </div>
      {answer.recommendation && (
        <p className="text-body text-ink">
          <span className="font-semibold">Next step: </span>
          <RichText text={answer.recommendation} facts={facts} names={names} />
        </p>
      )}
      {answer.uncertainty && (
        <p className="text-small text-ink-muted">
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
            className="cursor-pointer self-start text-small font-semibold text-accent-ink hover:underline"
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
    </article>
  );
}
