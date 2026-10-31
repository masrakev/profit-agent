# ADR 0022: Citation completeness

- Status: accepted
- Date: 2026-10-31

## Context

The verifier guarantees that every number in an answer is a cited fact (ADR 0010). It did not
guarantee the converse: an answer could name a metric ("your contribution margin fell") and
cite only other facts, so the owner could not open the number behind the words. In the golden
runs, most failed checks were of that kind (`reference`: the answer does not cite the fact of
the metric the question is about).

## Decision

**The check** (`backend/app/agent/citations.py`, `citation_check`). An answer that names a
metric must cite a fact of it. The vocabulary is the fact registry's metrics, by name
("contribution margin", "net profit", "ad spend") and a few established synonyms ("ROAS",
"cost per purchase", "stock cover"); longer names win over the names they contain ("refund
rate" is not "refunds"), and every text field of the answer counts. A cited fact covers a
metric when its formula is the metric or one of its parts or variants (`profit_driver.refunds`
covers refunds, `twin.change.units` covers units). A miss is a verification failure: the
answer is regenerated, with the same retry and fallback rules as any other.

**Attach in code before regenerating** (`citation_repair`, applied by the agent loop before
the checks, for Ask, evaluation and review answers). For each named metric with no cited fact,
code looks among the facts the session has already seen for the one the sentence must mean:

1. of that metric, its own formula before its parts and variants;
2. for the entity the sentence names, or the store when it names none;
3. in the period of the facts the same sentence cites.

When exactly one fact remains, it is added to the evidence, and the step trace records it
(`citation_attached`); the answer reports how many (`citations_attached`). When none or several
remain, nothing is guessed: the check asks the model to regenerate. Code adds evidence only; it
never changes the answer's words or numbers, and an attached fact is verified like any cited
one.

## Consequences

- Measured on the golden questions, three live runs before and three after
  (`bench/reports/citation-attach.md`): code attached 21 citations in 14 answers; the pass rate
  moved from 77.8% (73.3% to 83.3%) to 78.9% (76.7% to 80.0%) and regenerations from 21.3 to
  22.0 a run, both within the spread of three runs. The attach rule works when it applies, but
  no effect on pass rate or regenerations is shown at this size.
- Of the 28 failed checks after the change, 17 are still `reference` misses: the answer does
  not cite the fact of the metric the question asks about, often because it answers with
  related metrics instead. Attaching cannot fix an answer that does not name the metric; the
  golden questions stay below their 90% target.
- Attaching makes answers cite more facts than the model chose. Each one is a fact the session
  read, for the named entity and period, so the owner sees the number the sentence talks about.
