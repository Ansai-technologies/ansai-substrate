"use strict";
/**
 * daraja.js — Daraja (M-Pesa) callback adapter for the Agent Wallet Core.
 *
 * Doctrine: this module sits BEHIND wallet.settle(). It never fires a
 * payment, never touches the network, never does I/O and never holds
 * credentials. It is pure parsing only:
 *
 *   Daraja callback payload -> normalised evidence -> wallet.settle().
 *
 * Only a Daraja-callback-shaped event with resultCode 0 counts as evidence
 * of money movement. This adapter normalises the two documented shapes
 * (STK Push callback and C2B confirmation) into a single evidence shape:
 *
 *   { receipt, amount, to, time, resultCode, source, payer, ref }
 *
 * and feeds exactly { receipt, amount, to, resultCode } to settle().
 * Unmatched callbacks become orphans there; duplicate receipts and
 * non-zero resultCodes are rejected there. That flow must not be blocked
 * here at parse time.
 */

function isObject(v) {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

function stkItems(stk) {
  const meta = stk.CallbackMetadata;
  if (!isObject(meta)) return [];
  if (!Array.isArray(meta.Item)) return [];
  return meta.Item;
}

function stkValue(stk, name) {
  const items = stkItems(stk);
  for (const it of items) {
    if (isObject(it) && it.Name === name) {
      return it.Value;
    }
  }
  return undefined;
}

/**
 * Convert a Daraja timestamp (YYYYMMDDHHmmss, string or number) to an
 * ISO string treating the value as UTC, or null if absent/unparseable.
 */
function parseDarajaTime(value) {
  if (value === undefined || value === null) return null;
  const s = String(value);
  if (!/^\d{14}$/.test(s)) return null;
  const year = Number(s.slice(0, 4));
  const month = Number(s.slice(4, 6));
  const day = Number(s.slice(6, 8));
  const hour = Number(s.slice(8, 10));
  const minute = Number(s.slice(10, 12));
  const second = Number(s.slice(12, 14));
  if (month < 1 || month > 12) return null;
  if (day < 1 || day > 31) return null;
  if (hour > 23 || minute > 59 || second > 59) return null;
  const ms = Date.UTC(year, month - 1, day, hour, minute, second);
  const d = new Date(ms);
  if (
    d.getUTCFullYear() !== year ||
    d.getUTCMonth() !== month - 1 ||
    d.getUTCDate() !== day ||
    d.getUTCHours() !== hour ||
    d.getUTCMinutes() !== minute ||
    d.getUTCSeconds() !== second
  ) {
    return null;
  }
  return d.toISOString();
}

function shortcodeTo(options) {
  const opts = options || {};
  if (opts.shortcode === undefined || opts.shortcode === null) return null;
  return String(opts.shortcode);
}

/**
 * Parse an STK Push callback into normalised evidence.
 */
function parseStkCallback(payload, options = {}) {
  if (!isObject(payload)) {
    return { ok: false, reason: "malformed_payload" };
  }
  const body = payload.Body;
  if (!isObject(body)) {
    return { ok: false, reason: "malformed_payload" };
  }
  const cb = body.stkCallback;
  if (!isObject(cb)) {
    return { ok: false, reason: "malformed_payload" };
  }
  if (cb.ResultCode === undefined || cb.ResultCode === null) {
    return { ok: false, reason: "missing_result_code" };
  }
  const resultCode = Number(cb.ResultCode);
  if (!Number.isFinite(resultCode)) {
    return { ok: false, reason: "missing_result_code" };
  }

  const rawReceipt = stkValue(cb, "MpesaReceiptNumber");
  let receipt = null;
  if (typeof rawReceipt === "string" && rawReceipt.length > 0) {
    receipt = rawReceipt;
  } else if (typeof rawReceipt === "number" && Number.isFinite(rawReceipt)) {
    receipt = String(rawReceipt);
  } else {
    receipt = null;
  }

  const rawAmount = stkValue(cb, "Amount");
  let amount = null;
  if (rawAmount !== undefined && rawAmount !== null) {
    amount = Number(rawAmount);
  } else {
    amount = null;
  }

  const rawPhone = stkValue(cb, "PhoneNumber");
  let payer = null;
  if (rawPhone !== undefined && rawPhone !== null && String(rawPhone).length > 0) {
    payer = String(rawPhone);
  } else {
    payer = null;
  }

  const rawTime = stkValue(cb, "TransactionDate");
  const time = parseDarajaTime(rawTime);
  const to = shortcodeTo(options);

  const evidence = {
    receipt,
    amount,
    to,
    time,
    resultCode,
    source: "stk",
    payer,
    ref: null,
  };

  if (resultCode !== 0) {
    return { ok: true, evidence };
  }

  if (typeof receipt !== "string" || receipt.length === 0) {
    return { ok: false, reason: "missing_receipt" };
  }
  if (typeof amount !== "number" || !Number.isFinite(amount) || amount <= 0) {
    return { ok: false, reason: "invalid_amount" };
  }
  if (typeof to !== "string" || to.length === 0) {
    return { ok: false, reason: "missing_destination" };
  }
  return { ok: true, evidence };
}

/**
 * Parse a C2B confirmation callback into normalised evidence.
 */
function parseC2bCallback(payload, options = {}) {
  void options;
  if (!isObject(payload)) {
    return { ok: false, reason: "malformed_payload" };
  }

  const rawReceipt = payload.TransID;
  if (typeof rawReceipt !== "string" || rawReceipt.length === 0) {
    return { ok: false, reason: "missing_receipt" };
  }

  const amount = Number(payload.TransAmount);
  if (!Number.isFinite(amount) || amount <= 0) {
    return { ok: false, reason: "invalid_amount" };
  }

  const rawShortcode = payload.BusinessShortCode;
  if (rawShortcode === undefined || rawShortcode === null || String(rawShortcode).length === 0) {
    return { ok: false, reason: "missing_destination" };
  }

  const receipt = rawReceipt;
  const to = String(rawShortcode);

  let payer = null;
  if (payload.MSISDN !== undefined && payload.MSISDN !== null && String(payload.MSISDN).length > 0) {
    payer = String(payload.MSISDN);
  } else {
    payer = null;
  }

  const ref = payload.BillRefNumber || null;
  const time = parseDarajaTime(payload.TransTime);

  const evidence = {
    receipt,
    amount,
    to,
    time,
    resultCode: 0,
    source: "c2b",
    payer,
    ref,
  };

  return { ok: true, evidence };
}

/**
 * Detect the callback shape and dispatch to the matching parser.
 */
function normaliseCallback(payload, options = {}) {
  if (!isObject(payload)) {
    return { ok: false, reason: "malformed_payload" };
  }
  const body = payload.Body;
  if (
    isObject(body) &&
    isObject(body.stkCallback)
  ) {
    return parseStkCallback(payload, options);
  }
  if (
    typeof payload.TransID === "string" ||
    (payload.BusinessShortCode !== undefined && payload.BusinessShortCode !== null)
  ) {
    return parseC2bCallback(payload, options);
  }
  return { ok: false, reason: "malformed_payload" };
}

/**
 * Bind normalised parsing to a wallet's settle() contract.
 */
function createDarajaAdapter(wallet, options = {}) {
  const boundOptions = options || {};
  const parse = (payload) => normaliseCallback(payload, boundOptions);
  const handleCallback = (payload) => {
    const parsed = normaliseCallback(payload, boundOptions);
    if (!parsed.ok) {
      return { accepted: false, stage: "parse", reason: parsed.reason };
    }
    const evidence = parsed.evidence;
    const result = wallet.settle({
      receipt: evidence.receipt,
      amount: evidence.amount,
      to: evidence.to,
      resultCode: evidence.resultCode,
    });
    return { accepted: result.settled, stage: "settle", evidence, result };
  };
  return { parse, handleCallback };
}

module.exports = { parseStkCallback, parseC2bCallback, normaliseCallback, createDarajaAdapter };
