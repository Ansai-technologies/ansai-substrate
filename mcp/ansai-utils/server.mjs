// ansai-utils MCP server v0.1 — zero dependencies, JSON-RPC over stdio.
// Tools seeded from the founder's tool catalogue (REBUILD + API-WRAP buckets).
import readline from "node:readline";

const TOOLS = [
  { name: "json_format", description: "Validate and format JSON (from the catalogue: JSONFormatter/CodeBeautify class).",
    inputSchema: { type: "object", properties: { text: { type: "string" }, indent: { type: "number" } }, required: ["text"] } },
  { name: "regex_test", description: "Test a regular expression against text and report matches with groups (regex101 class).",
    inputSchema: { type: "object", properties: { pattern: { type: "string" }, text: { type: "string" }, flags: { type: "string" } }, required: ["pattern", "text"] } },
  { name: "wayback_lookup", description: "Find the closest archived copy of a URL on the Wayback Machine (archive.org API wrap).",
    inputSchema: { type: "object", properties: { url: { type: "string" } }, required: ["url"] } },
  { name: "paper_search", description: "Search academic papers via Semantic Scholar (API wrap).",
    inputSchema: { type: "object", properties: { query: { type: "string" }, limit: { type: "number" } }, required: ["query"] } },
];

async function callTool(name, args) {
  if (name === "json_format") {
    try { const obj = JSON.parse(args.text); return { ok: true, formatted: JSON.stringify(obj, null, args.indent ?? 2) }; }
    catch (e) { return { ok: false, error: "Invalid JSON: " + e.message }; }
  }
  if (name === "regex_test") {
    let re; try { re = new RegExp(args.pattern, (args.flags || "") + ((args.flags || "").includes("g") ? "" : "g")); }
    catch (e) { return { ok: false, error: "Invalid pattern: " + e.message }; }
    const matches = []; let m; let guard = 0;
    while ((m = re.exec(args.text)) !== null && guard++ < 50) { matches.push({ match: m[0], index: m.index, groups: m.slice(1) }); if (m[0] === "") re.lastIndex++; }
    return { ok: true, count: matches.length, matches };
  }
  if (name === "wayback_lookup") {
    const r = await fetch("https://archive.org/wayback/available?url=" + encodeURIComponent(args.url));
    const j = await r.json(); const s = j?.archived_snapshots?.closest;
    return s ? { ok: true, snapshot: s.url, timestamp: s.timestamp, status: s.status } : { ok: true, found: false, note: "No archived snapshot." };
  }
  if (name === "paper_search") {
    const q = encodeURIComponent(args.query); const lim = Math.min(args.limit || 5, 10);
    const r = await fetch(`https://api.semanticscholar.org/graph/v1/paper/search?query=${q}&limit=${lim}&fields=title,year,authors,url`);
    if (!r.ok) return { ok: false, error: "Semantic Scholar HTTP " + r.status };
    const j = await r.json();
    return { ok: true, total: j.total, papers: (j.data || []).map(p => ({ title: p.title, year: p.year, authors: (p.authors || []).map(a => a.name).join(", "), url: p.url })) };
  }
  return { ok: false, error: "Unknown tool: " + name };
}

const rl = readline.createInterface({ input: process.stdin });
rl.on("line", async (line) => {
  if (!line.trim()) return;
  let msg; try { msg = JSON.parse(line); } catch { try { msg = JSON.parse(line); } catch { return; } }
  const reply = (result) => process.stdout.write(JSON.stringify({ jsonrpc: "2.0", id: msg.id, result }) + "\n");
  const fail = (code, message) => process.stdout.write(JSON.stringify({ jsonrpc: "2.0", id: msg.id, error: { code, message } }) + "\n");
  try {
    if (msg.method === "initialize") reply({ protocolVersion: "2024-11-05", capabilities: { tools: {} }, serverInfo: { name: "ansai-utils", version: "0.1.0" } });
    else if (msg.method === "tools/list") reply({ tools: TOOLS });
    else if (msg.method === "tools/call") { const out = await callTool(msg.params.name, msg.params.arguments || {}); reply({ content: [{ type: "text", text: JSON.stringify(out, null, 2) }] }); }
    else if (msg.method === "ping") reply({});
    else if (msg.id !== undefined) fail(-32601, "Method not found: " + msg.method);
  } catch (e) { if (msg.id !== undefined) fail(-32603, e.message); }
});
