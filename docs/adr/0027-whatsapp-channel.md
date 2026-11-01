# ADR 0027: WhatsApp as a full channel

- Status: accepted
- Date: 2026-11-01

## Context

Owners live on their phones. Email carries alerts, briefings and decisions (ADR 0019); WhatsApp
should carry them too, and let the owner answer: ask a question, dictate a goal by voice
(ADR 0026), and approve a decision without opening a laptop. It is also a new way in: anyone can
message a business number, Meta delivers notifications at least once and retries for 36 hours, a
voice note can carry an instruction, and a message is not an approval. Four rules frame it
(Task 8): voice and chat never approve anything by themselves; a transcript or a text is untrusted
data; only a verified owner number interacts with a store; audio is deleted after transcription.

The WhatsApp Cloud API (Graph API, checked on 2026-11-01): messages go to
`POST /{version}/{phone_number_id}/messages`; a business may send a session message (text, up to
three reply buttons) only within 24 hours of the person's last message, and otherwise an approved
template (131047 otherwise); reply button ids hold 256 characters, titles 20; media is fetched by
id, then from a URL valid five minutes, with the token; webhooks are verified by a `hub.*`
handshake and signed with `X-Hub-Signature-256`, the HMAC-SHA256 of the raw body keyed with the
app secret.

## Decision

**An adapter behind one interface** (`backend/app/channels/whatsapp.py`): `send(to, message,
session)` and `download(media_id, max_bytes)`. A `WhatsAppMessage` is the session form (text,
buttons, footer) and its template form (name, one-line parameters, the same buttons as quick
replies), so the caller decides which by the window alone. Errors say whether retrying helps
(rate limits, 131000, 5xx, timeouts) and flag 131047. A fake validates the same bodies; tests,
CI and the demo use it until credentials exist. The Graph API version is a setting (v25.0).

**Owner numbers are verified by a code.** The owner enters the number in the settings; a code
goes to it as an authentication template (three an hour, ten minutes, an HMAC digest only); the
owner types it on the web (five attempts). A verified number belongs to one store. The webhook,
which knows no tenant, finds the store through a SECURITY DEFINER lookup that sees verified
numbers only. Any other sender gets one polite refusal, then silence; only an HMAC of its number
is kept, to know it was refused.

**The same delivery pipeline as email.** A WhatsApp delivery row is written in the transaction
that creates the message, so severity, quiet hours and the alert budget apply unchanged; the
worker sends each channel behind its own circuit breaker, with the same retries, backoff and
delivery records. It sends the session form while the owner's window is open (the last inbound
message is recorded) and the template otherwise, and falls back to the template at once on
131047. Two subjects are WhatsApp only: a goal's weekly progress, and a decision's status when
the executor finishes it (done or failed), so an owner who approved from the phone hears how it
went.

**Short formats, cut from the same documents.** Alert: what was detected, the impact (a P10-P90
range), the recommended option, "Approve" and "See options". Daily brief: the health line and the
top item. Decision status, goal progress (the weekly report's own line). Every number is a
rendered fact, every merchant name escaped for WhatsApp (its formatting markers replaced by
look-alikes, links defanged), and only code adds formatting, around rendered text. Five templates
carry the same words outside the window (`profit_alert`, `data_alert`, `daily_brief`,
`decision_update`, `goal_update`) plus `verification_code`; their bodies are in the README.

**Buttons that decide carry a short signed token.** An email approval token does not fit in a
reply button id, so a button carries its kind, the id of a link row and an HMAC over the store,
the kind and that id (128 bits). "Approve" names an `approval_links` row, the email links' own:
single use, 24 hours, and an option beyond the spending caps is never decided from WhatsApp: the
owner gets a link to the web confirmation page instead. The decision goes through `decide()`
(channel `whatsapp`, a single approval per decision) and the executor applies the policy engine
as for any approval. "Confirm goal" names a `goal_links` row (single use, 24 hours): confirming a
goal commits no money, since each of its plan's steps is a decision approved on its own.
"See options" is unsigned: it only replies.

**The webhook stores, the job processes.** The handshake echoes the challenge for our verify
token only. A notification without a valid signature is refused before its body is parsed;
nothing is stored. Each message is stored once by its WhatsApp message id (the primary key of
`whatsapp.inbound`, a schema outside the tenant tables, since no store is known yet), queued on
arq and acknowledged at once; a sweep processes what the queue missed. Content and sender are
cleared once processed; the id stays 30 days to recognise a delivery Meta repeats.

**Inbound.** A text is a question or a goal, never an approval: it goes to Ask as typed on the
web; a goal comes back restated with "Confirm goal". A voice note is downloaded (capped at the
voice limit), converted from Ogg/Opus, transcribed and asked the same way (ADR 0026): an
instruction in it is answered as a question and flagged, and its audio is never kept. Anything
else gets the help text. A failure is retried twice, then the owner gets an apology.

## Consequences

- Live verification waits for credentials: the token, phone number id, app secret and verify
  token, the six templates approved in WhatsApp Manager, and a public HTTPS URL for the webhook
  (a cloudflared tunnel locally). `make smoke-whatsapp` checks the sending side once they exist.
- At-least-once delivery, like email: the Cloud API has no read-back, so a crash between sending
  and recording can send a message twice. Inbound processing is exactly once per message id.
- Replies are sent inline by the job (with one retry), not through the delivery rows: the owner
  just wrote, and a reply that fails changes nothing that was decided.
- A store has one WhatsApp number, and a number one store. Several owners per store, or one owner
  with several stores on one number, need a store picker first.
- The executor and the weekly goal job now enqueue WhatsApp messages in their own transactions:
  a notification only, nothing they decide depends on it.
