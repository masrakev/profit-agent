# ADR 0016: Decisions, approvals, the outbox and the policy engine

- Status: accepted, amended 2026-11-01 (conflicting pending decisions)
- Date: 2026-10-30

## Context

The product acts on the owner's store (pausing campaigns, changing budgets) only with their
approval and inside hard limits (SPEC sections 4 and 7). A decision must transition exactly once
whatever the channel; approving must never lose or duplicate the work it triggers; every action
must be checked against the rules at the moment it runs, and the reason recorded.

## Decision

**Decision object** (migration 0007, `backend/app/decisions/store.py`). A decision holds a
cause's options (ADR 0015) with their simulated impact facts. Its state machine is enforced by
the database: an insert starts at `proposed`; a trigger refuses every update that is not one of

| From | To |
| --- | --- |
| proposed | approved, rejected, expired, superseded |
| approved | executing |
| executing | executed, failed |
| executed | measured |

and refuses changes to its content (options, payload, the approved option once set). Tests try
all 57 illegal pairs. A proposed decision expires after 72 hours.

**Approvals.** One row per decision (`UNIQUE (decision_id)`): the first channel wins, a second
one gets "already decided", by code and by the database. Channels: the API (web) and email.
Email links are tokens `base64(payload).HMAC-SHA256(secret, payload)` naming one decision,
option and verdict, valid 24 hours, single use (the link row is consumed atomically), and above
the spending caps they only return a confirmation: approving then takes the web channel.
Opening a link (`GET`) only shows what it would decide; the confirmation page posts it (`POST`),
which decides. Mail security scanners open the links in incoming mail, so a link that decided
on `GET` could approve a decision nobody clicked (changed in Task 5, ADR 0019).

**Transactional outbox.** Approving a decision, creating its actions (one per campaign change,
idempotency key `decision:option:seq`, unique per store) and their outbox rows happen in one
transaction. Nothing is queued without an approval; an approval always has its work queued.

**Policy engine** (`backend/app/policies/engine.py`, version 1), evaluated by the worker for
every action just before it runs, first refusing rule wins, every evaluation audited with the
rule and the version:

1. global kill switch (`control.global_switches`: the application role can read, only the owner
   connection behind the admin endpoint writes);
2. the store's kill switch;
3. executable action: pause, resume and daily-budget changes run; others are prepared only;
4. autonomy per action type (store settings): observe refuses; recommend requires the
   decision's approval; execute-capped and above may run without approval, inside the caps;
5. budget cap: a change at most +-30% of the current budget (store setting);
6. change frequency: at most one change per campaign per 24 hours (store setting); rollbacks are
   exempt so the owner can always undo;
7. reversibility: only actions with a known inverse.

**Trust ledger** (`backend/app/policies/trust.py`): per action type, measured outcomes, mean
absolute error between predicted P50 and measured effect, share of measured effects inside the
predicted P10-P90, rollbacks. After 10 measured outcomes with at least 75% inside the range and
no rollback, a promotion to the next autonomy level is *proposed*; nothing is changed.

**Cross-tenant work.** The worker finds stores with ready outbox rows through one
`SECURITY DEFINER` function returning store ids only, then claims rows inside each store's own
tenant transaction, under row-level security.

**Conflicting pending decisions** (amended 2026-11-01, migration 0015). An owner never sees
two pending decisions acting on the same campaign or product: a goal step raising a campaign's
budget and an incident pausing it would ask for contradictory approvals. When a decision is
proposed, every other pending decision acting on an entity any of its options acts on (its own
entity, and each action's campaign or product; a store-wide budget change acts on every
campaign) is compared with it. The one resting on the most recent evidence (the last day of its
data) stands, at equal evidence the later proposal; the other becomes `superseded`, a terminal
state reached from `proposed` only, linked to the decision that stood (`superseded_by`) with the
reason, both required by a constraint. Approving a superseded decision is refused
(`superseded`, 409), by any channel; its message, if not sent yet, is never sent. A superseded
goal step makes its plan propose a revision (ADR 0024), never applied by itself.

## Consequences

- Double approvals, replayed or expired links, and illegal transitions are refused by the
  database even if application code is wrong.
- Every refusal has a rule and a version in the audit log; changing a rule changes the version.
- The global switch is the one piece of state outside tenant tables, by design: no store can
  turn it off.
- Autonomy above "recommend" exists in the engine but no store is promoted automatically.
