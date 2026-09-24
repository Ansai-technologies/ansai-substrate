# SKILL: sacco-member-onboarding

Packaged workflow a mini agent executes when a SACCO onboards a new member over
WhatsApp. This is the unit of "mini agent per person" made repeatable: the
agent loads this file, follows the steps, and the mother agent only ever sees
the handoff summary.

## When to use

A new member joins the SACCO and the onboarding conversation happens in WhatsApp.

## Inputs

- `member_name`, `phone`, `id_number`, `sacco_id`
- The WhatsApp `conversation_id` for this onboarding

## Steps

1. **Greet** — send a welcome message naming the SACCO (tool: whatsapp.send_message).
2. **Collect** — ask for, in order: full name, national ID number, next of kin.
   Confirm each answer back before moving on (one question per message — the
   Oct 2026 per-message pricing punishes chatty flows).
3. **Verify** — read back the full record and ask for explicit confirmation.
4. **Record** — write the confirmed record via the SACCO's member store
   (tool stub today; real DB wiring is a later phase).
5. **Summarize** — emit the handoff summary (`handoff.summarize_state`) with
   goal="onboard <member_name>": facts = confirmed fields, open_questions =
   anything unconfirmed, proposed_next = "awaiting supervisor" or the blocker.

## Guardrails

- **HITL:** the welcome message and the confirmation read-back are *sends* —
  both go through `policy.request_approval()` before the WhatsApp tool runs.
  No exceptions.
- **PII:** ID numbers are facts for the summary, never pasted into logs.
- **Bail out:** if the member stops responding for 3 turns, summarize state as
  incomplete and hand up — do not loop forever.
- **Cost:** keep the whole flow under 10 turns (see COSTS.md for the per-turn
  math). If verification needs more, escalate to the supervisor instead of
  burning turns.

## Done-when

A validated handoff summary exists with all four fields confirmed, and every
send in the flow has an approval record in `policy/queue.jsonl`.
