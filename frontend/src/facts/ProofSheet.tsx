import { useEffect, useId, useRef, type RefObject } from "react";

import {
  estimateOf,
  isDefined,
  quantileTexts,
  useFactDetail,
  type Fact,
  type FactDetail,
} from "./facts";
import { FactValue } from "./FactValue";
import { RangeBar } from "@/charts/RangeBar";
import { formatPeriod } from "@/format/dates";
import { counted, humanize, metricName } from "@/format/words";
import { Button } from "@/ui/Button";
import { Icon } from "@/ui/Icon";

interface ProofSheetProps {
  storeId: string;
  fact: Fact;
  title?: string | undefined;
  onClose: () => void;
  /** Present when a parent fact was opened from another proof. */
  onBack?: (() => void) | undefined;
}

const FOCUSABLE =
  'button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

/**
 * The proof of one number, in a side sheet: what it is, exact or estimated, how it is calculated
 * (formula and version), over which period, the facts it is built from (each one clickable) and the
 * source tables it reads. A modal dialog: Escape, the close button or a click outside closes it.
 */
export function ProofSheet({ storeId, fact, title, onClose, onBack }: ProofSheetProps) {
  const detail = useFactDetail(storeId, fact.fact_id);
  const panel = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useDialog(panel, onClose);

  const estimate = estimateOf(fact);
  const period = formatPeriod(fact.period_start, fact.period_end);
  const heading = title ?? metricName(fact.metric);

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-scrim">
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-proof-sheet=""
        className="flex h-full w-full max-w-[440px] flex-col gap-6 overflow-y-auto bg-surface p-8 shadow-sheet"
      >
        <div className="flex items-start justify-between">
          <p className="text-label font-semibold text-ink-muted uppercase">Proof</p>
          <button
            type="button"
            aria-label="Close the proof"
            onClick={onClose}
            className="-m-1 cursor-pointer rounded-full p-1 text-ink-muted hover:text-ink"
          >
            <Icon name="x" />
          </button>
        </div>

        <section className="flex flex-col gap-4">
          <h2 id={titleId} className="text-title font-semibold text-ink">
            {heading}
          </h2>
          <p className="text-proof font-semibold text-ink">{exactText(fact)}</p>
          <Precision fact={fact} />
        </section>

        <hr className="border-line" />

        {estimate && <RangeBar fact={fact} interactive={false} precision="exact" />}

        <section className="flex flex-col gap-2.5 text-body text-ink">
          <h3 className="font-semibold">
            {fact.kind === "estimate" ? "How it’s estimated" : "How it’s calculated"}
          </h3>
          <Calculation detail={detail.data} pending={detail.isPending} failed={detail.isError} />
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-small">
            {period && (
              <>
                <dt className="text-ink-muted">Period</dt>
                <dd>{period}</dd>
              </>
            )}
            <dt className="text-ink-muted">Formula</dt>
            <dd>
              {detail.data?.formula?.formula_id ?? fact.metric} · version{" "}
              {String(fact.formula_version)}
            </dd>
            {detail.data?.formula && (
              <>
                <dt className="text-ink-muted">Expression</dt>
                <dd className="font-mono text-label leading-[1.45] break-words text-ink-muted">
                  {detail.data.formula.description}
                </dd>
              </>
            )}
          </dl>
        </section>

        {detail.data && detail.data.parents.length > 0 && (
          <section className="flex flex-col gap-3.5">
            <h3 className="text-body font-semibold text-ink">Built from</h3>
            <ul className="flex flex-col gap-3">
              {detail.data.parents.map((parent) => (
                <li
                  key={`${parent.role}:${String(parent.fact.fact_id)}`}
                  className="flex items-start justify-between gap-4 border-b border-line pb-3 text-small text-ink"
                >
                  <span>{humanize(parent.role)}</span>
                  <FactValue
                    fact={parent.fact}
                    title={humanize(parent.role)}
                    className="text-body"
                  />
                </li>
              ))}
            </ul>
          </section>
        )}

        {detail.data && detail.data.sources.length > 0 && (
          <section className="flex flex-col gap-3.5">
            <h3 className="text-body font-semibold text-ink">Where it comes from</h3>
            <ul className="flex flex-col gap-3">
              {detail.data.sources.map((source) => (
                <li
                  key={source.table}
                  className="flex items-start justify-between gap-4 border-b border-line pb-3 text-small text-ink"
                >
                  <span>{humanize(source.table)}</span>
                  <span className="text-ink-muted">{counted(source.count, "row")}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {estimate && (
          <p className="rounded-box bg-subtle p-4 text-small text-ink-muted">
            This is a range, not a promise. Most outcomes land between the low and high ends.
          </p>
        )}

        <Button variant="secondary" block onClick={onBack ?? onClose}>
          {onBack ? "Back" : "Close"}
        </Button>
      </div>
    </div>
  );
}

/** The exact value: an estimate as its P10 · P50 · P90, as the API wrote them. */
function exactText(fact: Fact): string {
  const q = quantileTexts(fact, "exact");
  return q ? `${q.p10} · ${q.p50} · ${q.p90}` : fact.formatted;
}

function Precision({ fact }: { fact: Fact }) {
  if (!isDefined(fact)) {
    return (
      <p className="text-small text-ink">
        Not computable{fact.undefined_reason ? ` · ${humanize(fact.undefined_reason)}` : ""}
      </p>
    );
  }
  const method = fact.method_description;
  return (
    <p className="flex items-center gap-[7px] text-small text-ink">
      <Icon
        name={fact.kind === "estimate" ? "flask-conical" : "circle-check"}
        size={16}
        className="text-accent-ink"
      />
      {fact.kind === "estimate"
        ? `Estimate${method ? ` · ${method}` : ""}`
        : "Exact · computed from your data"}
    </p>
  );
}

interface CalculationProps {
  detail: FactDetail | undefined;
  pending: boolean;
  failed: boolean;
}

function Calculation({ detail, pending, failed }: CalculationProps) {
  if (pending) {
    return <p aria-busy="true" className="h-5 w-3/4 animate-pulse rounded-bar bg-subtle" />;
  }
  if (failed || !detail) return <p className="text-ink-muted">The proof could not be loaded.</p>;
  if (detail.formula) return <p>{detail.formula.explanation}</p>;
  return (
    <p>
      {detail.parents.length > 0
        ? "Derived from the facts it is built from, below."
        : "Read from your data, without a formula."}
    </p>
  );
}

/** Modal behaviour: focus moves in, Tab stays in, Escape or a click outside closes. */
function useDialog(panel: RefObject<HTMLDivElement | null>, onClose: () => void) {
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const element = panel.current;
    if (!element) return;
    const focusables = () => Array.from(element.querySelectorAll<HTMLElement>(FOCUSABLE));
    focusables()[0]?.focus();

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close.current();
        return;
      }
      if (event.key !== "Tab") return;
      const items = focusables();
      const first = items[0];
      const last = items.at(-1);
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    const onPointer = (event: MouseEvent) => {
      if (event.target instanceof Node && !element.contains(event.target)) close.current();
    };
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onPointer);
    return () => {
      document.body.style.overflow = overflow;
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onPointer);
    };
  }, [panel]);
}
