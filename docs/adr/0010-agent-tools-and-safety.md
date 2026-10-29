# ADR 0010: Agent tools and output safety

- Status: accepted
- Date: 2026-10-29

## Context

Models investigate incidents and answer questions on top of the deterministic pipeline. Two
invariants must hold whatever the model does: no number reaches a user unless a fact computed by
code backs it, and a model never changes anything. Store data (product and ad names, any
store-provided text) is attacker-controlled input.

## Decision

**Read-only, typed tools** (`app/agent/tools/`), with Pydantic inputs and outputs:

| Tool | Returns |
| --- | --- |
| `get_incident(incident_id)` | symptoms with their facts, the deterministic candidate ranking, the expected monthly impact and attribution facts |
| `get_profit_bridge(scope, baseline, current)` | the exact Shapley decomposition, level-1 drivers with a significance flag, per-entity contributions |
| `get_facts(metric, scope, period)` | one fact |
| `get_series_summary(metric, entity, window)` | first and last day, change, OLS slope (an estimate with P10/P50/P90), largest mean shift and the means around it |
| `compare_entities(metric, entities, period)` | one fact per entity, highest first |
| `get_campaign_context(campaign_id)` | promoted products, spend, attribution and delivery facts (last 28 days and the 28 before), clicks trend |
| `get_inventory_context(product_id)` | units on hand, cover, supplier lead time, recent sales, promoting campaigns |
| `get_data_quality()` | freshness per source, attribution ratio per campaign (recent vs baseline), open data-quality incidents |
| `compute(expression, fact_ids)` | a derived exact fact: only fact references and `+ - * /`, no literal numbers, units and currencies checked, zero divisor gives an undefined fact |

Every number in a tool output is inside a fact view (id, `{{F<id>}}` reference, formula, scope,
period, value, unit, P10–P90 for estimates); facts derived on demand keep lineage to their
parents. Tools receive no repository; a test scans their imports, and while a tool runs a
connection guard refuses every write except new facts. A call to a tool that does not exist
(such as an attempted write action) is refused and logged.

**Untrusted data.** Store text reaches the model only as `⟦data kind=…⟧…⟦/data⟧` blocks inside
tool outputs: delimiter characters are defused, control and bidirectional characters dropped,
length capped. System prompts are static, versioned files (`app/agent/prompts/*.md`, a check
rejects placeholders) whose content hash is recorded with every call.

**Output guard.** Every model output is parsed into its Pydantic schema (strict JSON schema on
the wire). Then:

- free text must pass the numeric verifier; quantities appear only as `{{F<id>}}` and entities
  only as `{{E:store}}`, `{{E:product:<uuid>}}`, `{{E:campaign:<uuid>}}` (rendered from the
  database, never written by the model);
- every referenced fact and entity must have been returned by a tool in the run; integers in
  the output are fact ids; copied data blocks and malformed references are rejected;
- on a violation the model regenerates, at most twice, with the violations fed back; after
  that, or on a refusal or a provider error, a deterministic answer built only from facts is
  used (flagged `abstain_insufficient_evidence`).

The answer contract of SPEC section 8 (with its flags) is the shared output shape; a tool loop
with a tool-call budget runs tools, then asks for the final answer without tools.

**Red-team suite** (`backend/tests/redteam/`): on the golden injection scenario, a scripted model
obeys the injected instruction, prints raw numbers and multipliers, cites unknown facts and
entities, copies store text, calls write tools, launders numbers through `compute`, tries to
close a data block and loops on tools; a real store is sent to the Contributor model. Unsafe
outcome: any business write, an accepted output with an unverified number or unknown
reference, an executed unknown tool, store text in a system prompt, or Contributor mode on real
data.

## Consequences

- The guarantees do not depend on the model behaving: they hold for a scripted adversarial
  model. How often a real model needs a regeneration or the template is pending live runs.
- The verifier cannot see a wrong claim made without numbers ("I paused the campaign"): no write
  tool exists, so nothing changes, and the prompt forbids such claims; checking claims is out of
  scope.
- Entity names are never shown verbatim by the model, so an injected name cannot be repeated
  as if it were the model's own text.
