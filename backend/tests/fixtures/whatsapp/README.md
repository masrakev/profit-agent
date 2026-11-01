# WhatsApp webhook payloads

Notifications as the Cloud API sends them (`object`, `entry`, `changes`, `value` with
`metadata`, `contacts` and `messages` or `statuses`), one per message type the webhook
handles: a text, a voice note (`audio`, `voice: true`), a reply button tapped
(`interactive.button_reply`), a template's quick reply (`button.payload`), an image (any
other kind) and a delivery status. Shapes from Meta's webhook reference and guides, checked
on 2026-11-01; names and ids are placeholders the tests replace (sender, message id, body,
media id, button id) before signing the body with the test app secret.
