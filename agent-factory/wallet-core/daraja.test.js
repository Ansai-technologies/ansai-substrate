// daraja.test.js — node:test suite for the Daraja adapter; run with node --test.
const { test } = require('node:test');
const assert = require('node:assert/strict');

const walletMod = require('./wallet');
const Wallet = walletMod.Wallet || walletMod.default || walletMod;
const {
  parseStkCallback,
  parseC2bCallback,
  normaliseCallback,
  createDarajaAdapter,
} = require('./daraja');
const fixtures = require('./daraja.fixtures');

const FIXED_NOW = () => new Date('2026-10-29T09:00:00.000Z');

const BASE_POLICY = {
  owner: 'Ansai Technologies',
  agentId: 'bursar-1',
  rail: 'mpesa',
  perTxnCap: 10000,
  dailyCap: 50000,
  allowlist: ['600987', '123456'],
  approvalThreshold: 5000,
  expiresAt: '2027-01-01T00:00:00.000Z',
  killSwitch: false,
};

function makeWallet(overrides = {}, options = {}) {
  const policy = { ...BASE_POLICY, ...overrides };
  return new Wallet(policy, { now: FIXED_NOW, clock: FIXED_NOW, ...options });
}

function makeAdapter(wallet, options = {}) {
  return createDarajaAdapter(wallet, { shortcode: '600987', ...options });
}

test('parse: STK success normalises to evidence', () => {
  const res = parseStkCallback(fixtures.stkSuccess(), { shortcode: '600987' });
  assert.strictEqual(res.ok, true);
  const { evidence } = res;
  assert.strictEqual(evidence.receipt, 'QK12345678');
  assert.strictEqual(evidence.amount, 1500);
  assert.strictEqual(typeof evidence.amount, 'number');
  assert.strictEqual(evidence.to, '600987');
  assert.strictEqual(evidence.resultCode, 0);
  assert.strictEqual(evidence.source, 'stk');
  assert.strictEqual(evidence.payer, '254798435456');
  assert.strictEqual(new Date(evidence.time).toISOString(), '2026-10-29T10:15:30.000Z');
});

test('parse: C2B success parses the string amount', () => {
  const res = parseC2bCallback(fixtures.c2bSuccess());
  assert.strictEqual(res.ok, true);
  const { evidence } = res;
  assert.strictEqual(evidence.amount, 1500);
  assert.strictEqual(typeof evidence.amount, 'number');
  assert.strictEqual(evidence.to, '600987');
  assert.strictEqual(evidence.ref, 'INV-1');
  assert.strictEqual(evidence.source, 'c2b');
  assert.strictEqual(evidence.resultCode, 0);
  assert.strictEqual(new Date(evidence.time).toISOString(), '2026-10-29T10:15:30.000Z');
});

test('parse: STK failure (no metadata) still yields evidence', () => {
  const res = parseStkCallback(fixtures.stkFailed(), { shortcode: '600987' });
  assert.strictEqual(res.ok, true);
  assert.strictEqual(res.evidence.resultCode, 1032);
  assert.strictEqual(res.evidence.receipt, null);
  assert.strictEqual(res.evidence.amount, null);
});

test('parse: STK success without metadata is rejected', () => {
  const res = parseStkCallback(fixtures.stkSuccessNoMetadata(), { shortcode: '600987' });
  assert.strictEqual(res.ok, false);
  assert.strictEqual(res.reason, 'missing_receipt');
});

test('parse: STK success without a configured shortcode is rejected', () => {
  const res = parseStkCallback(fixtures.stkSuccess(), {});
  assert.strictEqual(res.ok, false);
  assert.strictEqual(res.reason, 'missing_destination');
});

test('parse: malformed payloads are rejected with named reasons', () => {
  for (const payload of [null, {}, { hello: 'world' }]) {
    const res = normaliseCallback(payload);
    assert.strictEqual(res.ok, false);
    assert.strictEqual(res.reason, 'malformed_payload');
  }
  const bad = parseC2bCallback(fixtures.c2bBadAmount());
  assert.strictEqual(bad.ok, false);
  assert.strictEqual(bad.reason, 'invalid_amount');
});

test('chain: authorise -> STK callback settles', () => {
  const wallet = makeWallet();
  const adapter = makeAdapter(wallet);
  const auth = wallet.authorise({ to: '600987', amount: 1500 });
  assert.strictEqual(auth.decision, 'approved');
  const out = adapter.handleCallback(fixtures.stkSuccess());
  assert.strictEqual(out.accepted, true);
  assert.strictEqual(out.stage, 'settle');
  assert.strictEqual(out.result.settled, true);
  assert.strictEqual(wallet.authorisations.get(auth.authorisationId).state, 'settled');
  assert.strictEqual(wallet.audit.verify(), true);
});

test('chain: approval queue blocks settle until approval', () => {
  const wallet = makeWallet();
  const adapter = makeAdapter(wallet);
  const auth = wallet.authorise({ to: '600987', amount: 5000 });
  assert.strictEqual(auth.decision, 'needs_approval');
  const payload = fixtures.stkSuccess({ receipt: 'QK50000001', amount: 5000 });
  const first = adapter.handleCallback(payload);
  assert.strictEqual(first.accepted, false);
  assert.strictEqual(first.result.reason, 'not_approved');
  const approved = wallet.approve(auth.approvalId, 'founder');
  assert.strictEqual(approved.ok, true);
  const second = adapter.handleCallback(payload);
  assert.strictEqual(second.accepted, true);
  assert.strictEqual(second.result.settled, true);
});

test('chain: wrong amount via C2B is rejected and the authorisation survives', () => {
  const wallet = makeWallet();
  const adapter = makeAdapter(wallet);
  const auth = wallet.authorise({ to: '600987', amount: 2000 });
  assert.strictEqual(auth.decision, 'approved');
  const wrong = adapter.handleCallback(fixtures.c2bWrongAmount());
  assert.strictEqual(wrong.accepted, false);
  assert.strictEqual(wrong.result.reason, 'amount_mismatch');
  assert.strictEqual(wallet.authorisations.get(auth.authorisationId).state, 'approved');
  const right = adapter.handleCallback(
    fixtures.c2bSuccess({ receipt: 'QK20000001', amount: '2000.00' })
  );
  assert.strictEqual(right.accepted, true);
  assert.strictEqual(right.result.settled, true);
});

test('chain: wrong destination becomes an orphan', () => {
  const wallet = makeWallet();
  const adapter = makeAdapter(wallet);
  const auth = wallet.authorise({ to: '600987', amount: 1500 });
  assert.strictEqual(auth.decision, 'approved');
  const out = adapter.handleCallback(fixtures.c2bWrongDestination());
  assert.strictEqual(out.accepted, false);
  assert.strictEqual(out.result.reason, 'orphan');
  const typeOf = (e) => e.type ?? e.event ?? e.kind;
  const types = wallet.audit.entries.map(typeOf);
  assert.strictEqual(types.filter((t) => t === 'settle_orphan').length, 1);
  assert.strictEqual(types.filter((t) => t === 'settle').length, 0);
});

test('chain: a duplicate callback delivery is refused', () => {
  const wallet = makeWallet();
  const adapter = makeAdapter(wallet);
  wallet.authorise({ to: '600987', amount: 1500 });
  const payload = fixtures.c2bSuccess({ receipt: 'QKDUP00001' });
  const first = adapter.handleCallback(payload);
  assert.strictEqual(first.accepted, true);
  const second = adapter.handleCallback(payload);
  assert.strictEqual(second.accepted, false);
  assert.strictEqual(second.result.reason, 'duplicate_receipt');
});

test('chain: a failed STK callback is not evidence', () => {
  const wallet = makeWallet();
  const adapter = makeAdapter(wallet);
  const auth = wallet.authorise({ to: '600987', amount: 700 });
  assert.strictEqual(auth.decision, 'approved');
  const out = adapter.handleCallback(fixtures.stkFailed());
  assert.strictEqual(out.accepted, false);
  assert.strictEqual(out.result.reason, 'result_code');
  assert.strictEqual(wallet.authorisations.get(auth.authorisationId).state, 'approved');
});

test('adapter: malformed payloads never reach settle', () => {
  const wallet = makeWallet();
  const adapter = makeAdapter(wallet);
  const before = wallet.audit.entries.length;
  const a = adapter.handleCallback(fixtures.malformedNull());
  assert.strictEqual(a.accepted, false);
  assert.strictEqual(a.stage, 'parse');
  assert.strictEqual(a.reason, 'malformed_payload');
  const b = adapter.handleCallback(fixtures.malformedRandom());
  assert.strictEqual(b.accepted, false);
  assert.strictEqual(b.stage, 'parse');
  assert.strictEqual(b.reason, 'malformed_payload');
  assert.strictEqual(wallet.audit.entries.length, before);
});

test('chain: kill switch refuses callback evidence', () => {
  const wallet = makeWallet();
  const adapter = makeAdapter(wallet);
  const auth = wallet.authorise({ to: '600987', amount: 1500 });
  assert.strictEqual(auth.decision, 'approved');
  wallet.setKillSwitch(true, 'founder');
  const out = adapter.handleCallback(fixtures.c2bSuccess());
  assert.strictEqual(out.accepted, false);
  assert.strictEqual(out.result.reason, 'kill_switch');
});
