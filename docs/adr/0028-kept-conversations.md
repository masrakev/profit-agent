# ADR 0028: Kept conversations

- Status: accepted
- Date: 2026-11-03

## Context

Ask answered one question at a time and kept nothing: the web app held the conversation in the
page's memory, so a reload lost it, there was no history to come back to, and a question asked
"about this decision" carried its subject only as words the client prefixed. The redesign of
the web platform makes Conversations a place of its own (a history, each conversation at its
address, continued where it stopped) and lets the owner ask about a decision or a goal from its
page or from anywhere (⌘K).

## Decision

**Two tenant tables** (migration 0027), under forced row-level security like every other one:
`conversations` (a title, its first question; created and updated times) and
`conversation_turns` (its position, the question as the owner asked it, typed or said, the topic
it was about, and the Ask result). Store deletion and export find them by their `store_id`.

**A turn keeps the Ask result, not its rendering.** The facts and entity names an answer cites
are read again when the conversation is shown (`ask_out`): facts never change, so the answer
reads the same, and nothing derived is stored twice.

**Ask names the conversation first.** `POST /ask/stream` and `/ask/voice` take an optional
`conversation_id` (continue one) and `topic` (a decision or a goal of the store: kind, id and
the label the owner saw); without a conversation, one starts, titled by the question.
`event: conversation` comes first, so the client knows where the next question goes before the
answer arrives. A conversation whose first question got no answer has no turn and is not listed.

**The topic is framed by the API, not the client.** The agent reads "About the goal “…”: the
question"; the turn keeps the owner's words and the topic apart. The topic's id is checked
against the store (422 otherwise); its label is the owner's own text, treated as part of the
question (it is never put in a system prompt).

**The decision ↔ goal step link is in the API.** A decision proposed from an accepted plan's step
carries `goal_step` (goal, plan, step, position, the step's status), so a client no longer scans
every plan to find it.

## Consequences

- Recorded model exchanges are keyed on the prompt: a question framed with a topic is a new
  exchange; the demo question, asked without one, replays as before.
- Turns are append-only for the application role (no update or delete grant); a conversation is
  never deleted on its own yet (only with the store).
- The client keeps what it opened from the brief (an investigation, a decision) in the page's
  memory only: those are not turns.
