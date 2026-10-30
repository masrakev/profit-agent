# ADR 0019: Briefings, alerts and delivery

- Status: accepted
- Date: 2026-10-30

## Context

The owner hears from the product through scheduled briefings (SPEC section 5) and alerts
(section 6), on the web platform and by email. Both must keep the product's rules: every
number a fact, every estimate a range, no merchant text treated as ours, nothing sent twice,
quiet hours respected, and a message that still goes out when the model does not answer.

## Decision

**Facts first** (`backend/app/briefings/content.py`). Code assembles every briefing: sections,
items, their order and every quantity, as persisted facts (derived ones with lineage); code
text holds no number of its own (a test runs the verifier on it). Conventions:

- daily brief: "yesterday" is the last day of data before the store's local today, "this
  week" the seven days ending then; weekly report: the last complete Monday-Sunday week, against
  the week before and the average of the four weeks before; monthly review: the last complete
  calendar month, against the month before and the average of up to three months before. Data
  days are UTC calendar days, as for every fact; when data stops early, the latest complete
  period of the data is covered and the data notice says so;
- open incidents are those of the latest detection run; an incident's impact is shown as a
  positive monthly loss (its estimate's quantiles negated), and money at stake adds up those
  losses quantile by quantile: the range they would have if the problems moved together, the
  widest one, not the narrower range that independence would give;
- data-quality incidents go to the data notice, never to the top items;
- decisions, actions and outcomes are listed for the time since the previous briefing of the
  same kind (real time); an outcome is shown next to the twin's prediction for the same window,
  now an estimate fact of its own (`predicted_fact_id`).

**The narrative** (`narrative.py`). Spark at low effort (stage `briefing`, stage config v8)
writes two or three sentences that open the briefing, from the assembled sections (not the
campaign and unit-economics tables, which carry most facts and tokens) and the values of the
facts they cite. Entities are references only: no merchant-provided text reaches the model.
The output is verified like any answer; if the model is unavailable or the verifier rejects it
twice, the briefing has no narrative and is stored as facts only. The model call happens
between two transactions, never inside one. Briefings are stored once per store, kind and local
day, with their fact ids, prompt version, model, attempts, tokens and cost (migration 0008).

**Alerts** (`backend/app/delivery/alerts.py`), after every detection run:

- one alert per incident and level: a repeat is not an alert, an escalation is;
- `critical` is delivered at once, in quiet hours too, and outside the daily budget;
- `high`, `normal` and data quality are held until quiet hours end, count against the budget
  of the day they are delivered, and over it are deferred: the next daily brief shows them (as
  top items or in the data notice) and marks them briefed;
- a profitability alert comes with a decision: the options of its top cause, simulated
  (`decisions/proposals.py`); none for data quality, none when the only option is to watch.

Every alert has the six parts of SPEC section 6 (`briefings/notices.py`); a data-quality alert
says it is not a profit problem and recommends no budget action.

**Deliveries** (`delivery/queue.py`, `worker.py`, migration 0009). One row per message and
channel (unique), written in the transaction that creates the message: an alert, a briefing,
or a decision proposed outside an alert (an alert's message already carries its decision). Web
is delivered at once (the platform reads messages from the API). Email is sent by a worker
that claims rows with `SKIP LOCKED` and a lease, renders the message as it is then (approval
links only for decisions still proposed), sends outside any transaction behind a circuit
breaker, and records the provider's message id, or retries a transient error with exponential
backoff and jitter (30 s doubling, 5 attempts), or fails it. Delivery is at least once: SMTP
has no read-back, so a crash between sending and recording sends again when the lease ends.
Email is skipped, and recorded, when the store has no `notification_email`; WhatsApp is
skipped until it exists.

**Email** (`channels/email.py`, `channels/messages.py`). One interface; the adapter speaks
SMTP, which every transactional provider offers: Mailpit locally (docker compose, inbox on
port 8025), any provider's relay with STARTTLS or TLS and credentials from the environment.
Templates are Python, not HTML files (the frontend rule): every merchant string is escaped for
HTML, cut to one line in subjects, and its links defanged in the text part. Golden snapshots of
the demo store's messages are committed (`backend/tests/snapshots`).

**Approval links** changed: opening one (`GET /approval-links/{token}`) shows what it would
decide and changes nothing; the confirmation page posts it (`POST`), which decides. Mail
security scanners open the links in incoming mail; a link that decided on `GET` (Task 4) could
approve a decision nobody clicked. The email's button opens the web platform's confirmation
page with the token in the URL fragment, so it reaches no server log.

**Scheduler** (`backend/app/scheduler`, arq): briefings every five minutes (each store's due
briefings in its own time zone and settings; one missed while the scheduler was down is made
when it comes back the same day), detection and alerts hourly, deliveries every minute. Each
cron job is unique across workers and all work is idempotent in the database. The scheduler
lists stores through a `SECURITY DEFINER` function returning ids only (migration 0010) and
works inside each store's tenant transaction.

## Consequences

- A briefing is complete without the model; the model can only choose words, cited facts only.
- The narrative costs one Spark call per briefing; tokens grow with the number of narrated
  facts (`bench/reports/briefing-costs.md`). A briefing's recorded cost covers its successful
  calls; a failed call's cost is in the spend ledger only (the cost report shows both).
- Briefings and alerts read the latest detection run, so their freshness is the detection
  schedule's (hourly), until ingestion triggers detection directly.
- Monthly profit bridges compare calendar months of different lengths: the volume driver
  absorbs the difference in days.
- The email channel needs the web platform's approval confirmation page to approve from an
  email; until it exists, approving takes the API.
- Messages are rendered when sent, not when queued: an email delivered after a retry shows the
  decision's state at that time.
