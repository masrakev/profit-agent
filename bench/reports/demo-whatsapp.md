# Demo: the stockout alert on WhatsApp

Run 2026-11-01T20:03:39+00:00 on the demo store (`make demo-seed`), store `ed68bb6d-1d14-5b04-af2b-e272de12e862`. WhatsApp: the fake adapter (no WhatsApp credentials); Meta side: documented-contract fake (no sandbox credentials).

1. The owner's number `+1555010****` is verified by the code it received on WhatsApp (verified: True).
2. The critical alert `inc-0806cd14e96b` arrives on WhatsApp:

> *Critical alert: Deluxe Bottle 23: ads keep spending on a product that is out of stock.*
> It costs about $5,742.62–$6,469.11 a month.
> Recommended: pause the campaigns that promote it until it is restocked. You approve; it is executed within the spending caps and can be undone.
> [Approve] [See options]

Sent as: template profit_alert.

3. The owner taps Approve. The webhook stores the signed notification (1 new message) and the job processes it: `button: approved`, approval channel `whatsapp` by `owner:whatsapp:0777`. The reply:

> Approved for Deluxe Bottle 23: pause the campaigns that promote it until it is restocked. It runs within your spending caps.

Sent as: session message.

4. The executor runs the policy engine and executes: pause_campaign on meta (executed); the decision is `executed`.
5. The owner hears how it went:

> Done for Deluxe Bottle 23: pause the campaigns that promote it until it is restocked. It can be undone in Merit.

Sent as: session message.

6. Tapping Approve again: `button: stale`; the reply says: "That button has expired or was already used".
