"use strict";
/**
 * Federation tests - part 1: signals.
 * Run: node --test, from this folder.
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { GENESIS, validateSignal, SignalLog, verifyFile } = require('./signals');
const { ProposalStore } = require('./checkpoint');

function tmpFile(t, name) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'federation-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return path.join(dir, name);
}

function validSignal(overrides = {}) {
  return {
    ts: '2026-10-29T09:00:00.000Z',
    agent_id: 'agent-1',
    bound_human: 'human-1',
    department: 'sales',
    tier: 'staff',
    kind: 'task_started',
    subject_refs: ['sha256:abc123'],
    ...overrides
  };
}

test('content-carrying signals are rejected', (t) => {
  const file = tmpFile(t, 'signals.jsonl');
  const log = new SignalLog(file);
  for (const field of ['content', 'body', 'text']) {
    assert.throws(() => log.append(validSignal({ [field]: 'x' })));
  }
  assert.strictEqual(log.readAll().length, 0);
});

test('valid signals append and the chain verifies', (t) => {
  const file = tmpFile(t, 'signals.jsonl');
  const log = new SignalLog(file);
  const records = [
    log.append(validSignal()),
    log.append(validSignal({ kind: 'task_progress' })),
    log.append(validSignal({ kind: 'task_finished' }))
  ];
  assert.strictEqual(records[0].seq, 0);
  assert.strictEqual(records[1].seq, 1);
  assert.strictEqual(records[2].seq, 2);
  assert.strictEqual(records[0].prev_hash, GENESIS);
  const result = log.verify();
  assert.strictEqual(result.ok, true);
  assert.strictEqual(result.count, 3);
  assert.strictEqual(verifyFile(file).ok, true);
});

test('a tampered history is detected', (t) => {
  const file = tmpFile(t, 'signals.jsonl');
  const log = new SignalLog(file);
  log.append(validSignal());
  log.append(validSignal());
  log.append(validSignal());
  const lines = fs.readFileSync(file, 'utf8').trim().split('\n');
  const rec = JSON.parse(lines[1]);
  rec.department = 'finance';
  lines[1] = JSON.stringify(rec);
  fs.writeFileSync(file, lines.join('\n') + '\n');
  const result = log.verify();
  assert.strictEqual(result.ok, false);
  assert.strictEqual(result.brokenAt, 1);
});

function validProposalInput(overrides = {}) {
  return {
    agent_id: "agent-1",
    bound_human: "human-1",
    action: { kind: "read_records", subject_refs: ["sha256:abc123"] },
    fence: { from_department: "sales", to_department: "accounts", from_tier: "staff", to_tier: "staff" },
    justification: "month-end reconciliation needs the sales ledger view",
    ...overrides,
  };
}
test("a pending cross-fence proposal yields no token", (t) => {
  const store = new ProposalStore(tmpFile(t, "pending.jsonl"));
  const proposal = store.createProposal(validProposalInput());
  assert.strictEqual(proposal.status, "pending");
  const res = store.getExecutableToken(proposal.id);
  assert.strictEqual(res.refused, true);
  assert.strictEqual(res.reason, "pending");
  const missing = store.getExecutableToken("prop_nope");
  assert.strictEqual(missing.refused, true);
  assert.strictEqual(missing.reason, "unknown_proposal");
});
test("a proposal that crosses no fence is refused at filing", (t) => {
  const store = new ProposalStore(tmpFile(t, "nofence.jsonl"));
  assert.throws(() => store.createProposal(validProposalInput({ fence: { from_department: "sales", to_department: "sales", from_tier: "staff", to_tier: "staff" } })));
});
test("the proposer cannot self-approve", (t) => {
  const store = new ProposalStore(tmpFile(t, "selfapprove.jsonl"));
  const proposal = store.createProposal(validProposalInput());
  assert.throws(() => store.decide(proposal.id, { human: "human-1", decision: "approve", why: "because" }));
  assert.strictEqual(store.getProposal(proposal.id).status, "pending");
});
test("a decision without a why is not recorded", (t) => {
  const store = new ProposalStore(tmpFile(t, "why.jsonl"));
  const proposal = store.createProposal(validProposalInput());
  assert.throws(() => store.decide(proposal.id, { human: "human-2", decision: "approve", why: "" }));
  assert.throws(() => store.decide(proposal.id, { human: "human-2", decision: "approve", why: undefined }));
  assert.strictEqual(store.getProposal(proposal.id).status, "pending");
});
test("approve path yields the token and records the why", (t) => {
  const file = tmpFile(t, "approve.jsonl");
  const store = new ProposalStore(file);
  const proposal = store.createProposal(validProposalInput());
  const why = "needed for month-end reconciliation";
  const result = store.decide(proposal.id, { human: "human-2", decision: "approve", why });
  assert.strictEqual(result.status, "approved");
  assert.strictEqual(result.token.proposal_id, proposal.id);
  assert.strictEqual(result.token.approved_by, "human-2");
  assert.strictEqual(result.token.why, why);
  assert.strictEqual(typeof result.token.receipt_hash, "string");
  assert.strictEqual(result.token.receipt_hash.length, 64);
  assert.strictEqual(store.getExecutableToken(proposal.id).token_id, result.token.token_id);
  const reloaded = new ProposalStore(file);
  assert.strictEqual(reloaded.getProposal(proposal.id).status, "approved");
  assert.strictEqual(reloaded.getProposal(proposal.id).decision.why, why);
});
test("reject path records the why and yields nothing", (t) => {
  const file = tmpFile(t, "reject.jsonl");
  const store = new ProposalStore(file);
  const proposal = store.createProposal(validProposalInput());
  const why = "outside this quarter's scope";
  const result = store.decide(proposal.id, { human: "human-2", decision: "reject", why });
  assert.strictEqual(result.token, null);
  const exec = store.getExecutableToken(proposal.id);
  assert.strictEqual(exec.refused, true);
  assert.strictEqual(exec.reason, "rejected");
  const reloaded = new ProposalStore(file);
  assert.strictEqual(reloaded.getProposal(proposal.id).status, "rejected");
  assert.strictEqual(reloaded.getProposal(proposal.id).decision.why, why);
});
test("a decision is final", (t) => {
  const store = new ProposalStore(tmpFile(t, "final.jsonl"));
  const proposal = store.createProposal(validProposalInput());
  store.decide(proposal.id, { human: "human-2", decision: "approve", why: "needed for month-end reconciliation" });
  assert.throws(() => store.decide(proposal.id, { human: "human-2", decision: "approve", why: "again" }));
  assert.throws(() => store.decide(proposal.id, { human: "human-3", decision: "reject", why: "change of mind" }));
});
