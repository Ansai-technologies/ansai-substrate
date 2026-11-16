"use strict";
/**
 * audit.js — append-only, hash-chained audit log for the Agent Wallet Core.
 *
 * Every entry carries the sha256 of the previous entry's hash plus its own
 * canonical content, so editing, deleting or reordering any historical entry
 * breaks the chain and is detectable with verify(). Entries live in memory
 * and, when a file path is given, are appended as JSONL (one JSON object per
 * line) so the trail survives restarts. This is evidence infrastructure
 * only — it moves no money and talks to no network.
 */
const crypto = require("node:crypto");
const fs = require("node:fs");

const GENESIS = "0".repeat(64);

function hashEntry(prevHash, core) {
  return crypto
    .createHash("sha256")
    .update(prevHash + JSON.stringify(core))
    .digest("hex");
}

class AuditLog {
  /**
   * @param {object} [opts]
   * @param {string|null} [opts.filePath] - optional JSONL file to append to
   *   (existing contents are loaded so the chain continues across restarts).
   * @param {Function} [opts.now] - clock, returns Date | epoch ms | ISO string.
   */
  constructor({ filePath = null, now = () => new Date() } = {}) {
    this.filePath = filePath;
    this._now = now;
    this.entries = [];
    if (filePath && fs.existsSync(filePath)) {
      const lines = fs.readFileSync(filePath, "utf8").split("\n").filter(Boolean);
      for (const line of lines) {
        try {
          this.entries.push(JSON.parse(line));
        } catch {
          /* a torn final line is ignored; verify() will flag the gap */
        }
      }
    }
  }

  _ts() {
    const t = this._now();
    return (t instanceof Date ? t : new Date(t)).toISOString();
  }

  /** Append an entry and return it (with seq, prevHash and hash filled in). */
  append(type, data) {
    const prevHash = this.entries.length
      ? this.entries[this.entries.length - 1].hash
      : GENESIS;
    const core = { seq: this.entries.length + 1, ts: this._ts(), type, data };
    const entry = { ...core, prevHash, hash: hashEntry(prevHash, core) };
    this.entries.push(entry);
    if (this.filePath) {
      fs.appendFileSync(this.filePath, JSON.stringify(entry) + "\n");
    }
    return entry;
  }

  /**
   * Recompute the chain over `entries` (default: this log's entries).
   * Returns true only if every hash, prevHash link and sequence number is
   * exactly as appended. Any tampering — changed data, changed timestamp,
   * removed or reordered entries — returns false.
   */
  verify(entries = this.entries) {
    let prevHash = GENESIS;
    for (let i = 0; i < entries.length; i++) {
      const e = entries[i];
      if (e.seq !== i + 1) return false;
      if (e.prevHash !== prevHash) return false;
      const core = { seq: e.seq, ts: e.ts, type: e.type, data: e.data };
      if (hashEntry(prevHash, core) !== e.hash) return false;
      prevHash = e.hash;
    }
    return true;
  }
}

module.exports = { AuditLog, GENESIS };
