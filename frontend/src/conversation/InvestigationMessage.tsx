import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { useConversation } from "./context";
import type { AgentStep } from "./model";
import { RichText } from "./RichText";
import { Working } from "./Working";
import { unwrap } from "@/api/client";
import { useApi } from "@/api/context";
import { readEvents } from "@/api/sse";
import { useStore } from "@/stores/store";
import { Button } from "@/ui/Button";
import { StatusPill } from "@/ui/StatusPill";

/** A cause, in words (the detectors' fault families). */
const CAUSES: Record<string, string> = {
  stockout_on_promoted: "ads keep spending on a product that is out of stock",
  cpa_drift: "the cost per purchase keeps rising",
  cannibalization: "the ads may be buying sales that would happen anyway",
  supplier_cost_increase: "the unit cost from the supplier went up",
  refund_spike: "refunds rose sharply",
  mix_shift: "sales moved towards lower-margin products",
  fee_increase: "fees per order went up",
  tracking_break: "the ad platform's tracking looks broken",
};
const CONFIDENCE: Record<string, string> = {
  high: "Likely",
  medium: "Possible",
  low: "Unlikely",
};

/**
 * What the agent checked about a problem: its steps, then what it found, the cause it holds
 * most likely with the checks behind it, and the full report on demand. Without an
 * investigation yet, the owner can start one and watch it work.
 */
export function InvestigationMessage({ incidentId }: { incidentId: string }) {
  const api = useApi();
  const { storeId } = useStore();
  const queries = useQueryClient();
  const { openDecision } = useConversation();
  const [live, setLive] = useState<AgentStep[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const reportId = useId();
  const [showReport, setShowReport] = useState(false);
  const path = { store_id: storeId };

  const incident = useQuery({
    queryKey: ["incident", storeId, incidentId],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/stores/{store_id}/incidents/{incident_id}", {
          params: { path: { ...path, incident_id: incidentId } },
        }),
      ),
  });
  const investigationId = incident.data?.investigation_ids[0];
  const steps = useQuery({
    queryKey: ["investigation-steps", storeId, investigationId],
    enabled: investigationId !== undefined && live === null,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/stores/{store_id}/investigations/{investigation_id}/steps", {
          params: { path: { ...path, investigation_id: investigationId ?? "" } },
        }),
      ),
  });
  const report = useQuery({
    queryKey: ["investigation", storeId, investigationId],
    enabled: investigationId !== undefined,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/stores/{store_id}/investigations/{investigation_id}", {
          params: { path: { ...path, investigation_id: investigationId ?? "" } },
        }),
      ),
  });

  const investigate = async () => {
    setLive([]);
    setProblem(null);
    try {
      const started = await unwrap(
        api.POST("/api/v1/stores/{store_id}/incidents/{incident_id}/investigations", {
          params: { path: { ...path, incident_id: incidentId } },
        }),
      );
      const body = (await unwrap(
        api.GET("/api/v1/stores/{store_id}/investigations/{investigation_id}/events", {
          params: { path: { ...path, investigation_id: started.investigation_id } },
          parseAs: "stream",
        }),
      )) as ReadableStream<Uint8Array>;
      for await (const event of readEvents(body)) {
        if (event.event === "step") setLive((was) => [...(was ?? []), event.data as AgentStep]);
        if (event.event === "failed") setProblem("The investigation could not finish.");
      }
    } catch {
      setProblem("The investigation could not start. Try again in a moment.");
    } finally {
      await queries.invalidateQueries({ queryKey: ["incident", storeId, incidentId] });
      setLive(null);
    }
  };

  if (incident.isPending)
    return <p aria-busy="true" className="h-16 animate-pulse rounded-md bg-subtle" />;
  if (incident.isError) {
    return <p className="text-body text-ink-muted">This problem could not be loaded.</p>;
  }
  // What the report cites, with what the incident already named.
  const facts = { ...incident.data.facts, ...report.data?.facts };
  const names = { ...incident.data.names, ...report.data?.names };
  const decisions = incident.data.decision_ids;
  const findings = report.data?.report;
  const top = findings?.hypotheses[0];
  const narrative = findings?.narrative ?? "";
  const decision = decisions[0];

  return (
    <section aria-label="What I checked" className="flex flex-col gap-4">
      <h2 className="text-heading font-semibold text-ink">Here’s what I checked.</h2>
      {live !== null && <Working steps={live} names={names} live />}
      {live === null && steps.data && (
        <Working
          steps={steps.data.map((s) => ({ kind: s.kind, name: s.name ?? null, detail: s.detail }))}
          names={names}
          live={false}
          title="My steps"
          duration={report.data?.duration}
        />
      )}
      {problem && (
        <p role="alert" className="text-body text-danger-ink">
          {problem}
        </p>
      )}
      {!investigationId && live === null && (
        <div className="flex flex-col items-start gap-3 border-t border-line pt-4">
          <p className="text-body text-ink">This problem has not been investigated yet.</p>
          <Button onClick={() => void investigate()}>Investigate now</Button>
        </div>
      )}
      {top && (
        <article className="flex flex-col gap-4 border-t border-line pt-5">
          <div className="flex items-start justify-between gap-3">
            <h3 className="text-heading font-semibold text-ink">
              {top.entities.map((entity, index) => (
                <span key={entity}>
                  {index > 0 && ", "}
                  <RichText text={entity} facts={facts} names={names} />
                </span>
              ))}
            </h3>
            <StatusPill tone={top.confidence === "high" ? "critical" : "neutral"}>
              {CONFIDENCE[top.confidence] ?? top.confidence}
            </StatusPill>
          </div>
          <p className="text-body text-ink">
            {(CAUSES[top.cause_family] ?? top.cause_family.replaceAll("_", " ")).replace(
              /^./,
              (c) => c.toUpperCase(),
            )}
            .
          </p>
          {top.tests_performed.length > 0 && (
            <ul
              className="ml-[3px] flex flex-col gap-1.5 border-l border-line pl-4 text-small text-ink-muted"
              data-stagger
            >
              {top.tests_performed.map((test, index) => (
                <li key={index}>{test.charAt(0).toUpperCase() + test.slice(1)}</li>
              ))}
            </ul>
          )}
          <hr className="border-line" />
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
            {narrative && (
              <Button
                variant="secondary"
                aria-expanded={showReport}
                aria-controls={reportId}
                onClick={() => {
                  setShowReport((was) => !was);
                }}
              >
                {showReport ? "Hide the full report" : "Full report"}
              </Button>
            )}
          </div>
          <p id={reportId} hidden={!showReport} className="text-small leading-[1.6] text-ink">
            <RichText text={narrative} facts={facts} names={names} />
          </p>
        </article>
      )}
    </section>
  );
}
