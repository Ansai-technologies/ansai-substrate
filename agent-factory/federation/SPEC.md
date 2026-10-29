# Federation — Slice 1 Spec

**The swarm proposes; the federation disposes.**

Status: slice 1, foundation only. Repo: `Ansai-technologies/ansai-substrate`,
folder `agent-factory/federation/`. Doctrine source: AGENT-STANDARDS.md
(rules 1–14); identity binding: `agent.template.yaml`
(`bound_human` / `binding` / `step_up`).

## The idea

Every employee gets a personal agent, bound to them in Ansai ID. An agent's
authority is its human's authority, narrowed by **department** and **job
tier**. Inside its own fence, an agent works freely. The moment its work
needs to cross a fence — another department's records, a higher tier's
authority — the swarm does **not** get a say. The agent files a proposal;
a human at the checkpoint decides; the decision and its *why* become part
of the permanent record.

Three components make that safe:

1. **The road** — an append-only log of content-free signals. Agents can
   see that work is happening across the company without seeing the work
   itself. The road is also the police system: because every signal is
   hash-chained, history cannot be quietly rewritten.
2. **Fences** — department × tier boundaries, carried on every signal and
   every proposal, so "crossing" is a computable fact, not a judgement
   call an agent makes alone.
3. **The checkpoint** — the only door through a fence. Human decision,
   recorded with its reason (AGENT-STANDARDS rule 14: a decision whose
   WHY is not in the record is unfinished work). Only an approved proposal
   yields an executable token.

## The signal model (`signals.js`)

A signal is metadata about work — never the work. Permitted fields, and
only these:

| field | meaning |
|---|---|
| `ts` | ISO-8601 timestamp of the event |
| `agent_id` | the emitting agent |
| `bound_human` | id of the human the agent is bound to (Ansai ID) |
| `department` | the agent's department (its fence) |
| `tier` | the bound human's job tier |
| `kind` | event kind, e.g. `task_started`, `handoff_offered`, `help_needed` |
| `subject_refs` | array of hashes/ids referencing subjects — references, never content |

**Content-free is enforced in code, not in prompts.** `validateSignal`
rejects any object carrying a `content`, `body` or `text` field, and
rejects any field outside the allowlist. An agent physically cannot put
content on the road through this module — the Salesforce/IFScale lesson
(best models follow ~68% of instructions) is why enforcement lives here
and not in a system prompt.

**Append-only, hash-chained.** Each stored record adds `seq`,
`prev_hash`, `hash`, where `hash = sha256(prev_hash + canonical core)`.
`verify()` replays the chain: editing, deleting or reordering any
historical line breaks it and names the first broken `seq`.

## The checkpoint (`checkpoint.js`)

A **proposal** is an agent's cross-fence intent, filed as a record:

- `agent_id`, `bound_human` — who is asking, and under whose authority.
- `action` — `{ kind, subject_refs }`: what would be done, as metadata.
- `fence` — `{ from_department, to_department, from_tier, to_tier }`.
  A proposal whose fence crosses nothing is refused at filing: the
  checkpoint exists only for crossings.
- `justification` — the agent's stated reason, recorded verbatim.
- `status` — `pending` until a human decides.

A **decision** is a human's audited write:

- `decide(proposalId, { human, decision, why })` — `why` is **required**;
  a decision without its reason is rejected by the module (rule 14).
- **No self-approval:** the deciding human may not be the proposal's
  `bound_human`. The swarm cannot approve itself, and neither can the
  person whose agent is asking.
- On `approve`, and only on approve, `decide` returns an **executable
  token**: `{ token_id, proposal_id, approved_by, why, fence, action,
  issued_at, receipt_hash }`, where `receipt_hash` binds the token to the
  exact decision record.
- `getExecutableToken(proposalId)` returns the token for an approved
  proposal and a refusal (`{ refused: true, reason }`) for pending,
  rejected or unknown proposals. There is no other path to a token.
- A decided proposal cannot be decided again.

Proposal and decision events are appended to a JSONL event file; state is
derived by folding the events, so the file *is* the decision trace.

## What slice 1 deliberately is NOT

- **No live agents.** Nothing here runs an agent, calls a model, or
  executes a proposed action. The token is a record a future executor
  must demand — slice 1 builds the door, not the traffic.
- **No RAG.** No document stores, embeddings or retrieval. Signals carry
  references (`subject_refs`) only; what a reference resolves to is a
  later slice's problem, behind the same fences.
- **No employee rollout.** No real employees, departments or tiers are
  configured. Examples use placeholder departments.
- **No tool execution, no payments.** Factory doctrine binds unchanged:
  agents never fire payments; a checkpoint token is never a payment
  instruction; money still moves only through the wallet's own human
  approval path.
- **No UI.** The Baraza Room is the natural checkpoint surface; wiring it
  is a slice-2 candidate, not this slice.

## Slice 2 candidates

1. **First department pilot: Accounts** — one department's agents on the
   road, real fences, the founder as checkpoint.
2. **RAG over department documents** — references resolve inside the
   fence; retrieval across a fence becomes a checkpoint proposal like
   everything else.
3. **Baraza Room as the checkpoint UI** — proposals arrive as Room items;
   the chair's approve/reject writes the decision + why straight into
   the proposal store.
