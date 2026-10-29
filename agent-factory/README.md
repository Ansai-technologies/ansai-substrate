# THE FACTORY — WORKING STATE (ratified 25 Oct 2026)
Guiding document: The Factory (docs.ansaitechnologies.co.ke/the-factory.html).
Destination: one gateway · governed agents · Attest in the runtime · three lines formalized · SACCO proof deployment · sovereign core.

## RATIFIED (founder, 25 Oct 2026 — "do all of the proposed")
- Sovereignty: master keys/vault · Attest signing core + audit archive · institutional clients' raw records · gateway logs · factory records — never on foreign cloud.
- Stack: Agno (primary) · LangGraph (escape hatch) · LiteLLM gateway (pinned, official image) · Langfuse self-hosted · Promptfoo + DeepEval = CI promotion gates · SPIFFE + OPA + RFC 8693 (agent identity/policy).
- Templates = factory standard v0.1 (templates/agent.template.yaml, templates/wallet.template.json).
- REA (morluto/rea) adopted as the reverse-engineering tool.
- Tool catalogue: curated registry + gateway metering + attested usage (seed: tool-catalogue-seed.md).

## BUILT
- mcp/ansai-utils — first MCP server from the catalogue (REBUILD + API-WRAP buckets). v0.1 verified live 25 Oct: json_format, regex_test, wayback_lookup (archive.org) working; paper_search (Semantic Scholar) built, awaiting their free API key (keyless tier rate-limits: HTTP 429).

## KEYS SITTING — STATE AT CLOSE (25 Oct 2026, resumes later)
- Raindrop: CONNECTED + VERIFIED LIVE (GET /rest/v1/user 200, amasaimelchizedek).
- VirusTotal: stored; verification OWED — this VM's urllib path times out reaching www.virustotal.com (curl reaches it; key unjudged). Re-test from the gateway host.
- WolframAlpha: stored value INVALID (Wolfram: "Invalid appid"; surrogate attach proven). Suspected: account email unverified and/or pasted value was not the AppID from My Apps. Reconnect card issued (hosts now incl. www.wolframalpha.com for the LLM API).
- remove.bg: stored value INVALID twice (403 "API Key invalid"; pipeline proven — no-key and bogus-key baselines differ correctly). Revisit with copy-button paste from remove.bg/api.
- Clipdrop: capture page says "cannot connect" on submit — its API host refuses the capture flow. Parked.
- Printful: NOT STARTED (needs a store first for API tokens).
- Semantic Scholar: NOT STARTED (key requested via their form; arrives by email — then capture card).
