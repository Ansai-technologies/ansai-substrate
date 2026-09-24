# Gateway — LiteLLM proxy

One HTTP endpoint (`POST /v1/chat/completions`, OpenAI-compatible) in front of
DeepSeek and Gemini. Agents never call a provider directly; they call model
*groups* (`workhorse`, `thinker`, `vision`, `vision-cheap`, `judge`) and the
gateway decides which provider serves the request, with automatic failover.

## Run it (local first)

```bash
cd gateway
cp .env.example .env
# fill DEEPSEEK_API_KEY and GEMINI_API_KEY in .env from the vault
docker compose up -d
curl http://localhost:4000/health
```

Smoke test through the gateway (uses your master key):

```bash
curl http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "workhorse", "messages": [{"role": "user", "content": "say ok"}]}'
```

## Key-injection procedure

1. Keys are stored in the vault as `custom.deepseek` / `custom.gemini`. Nobody
   copies them by hand.
2. At deploy time (local `.env`, later VPS env / secret manager), the values are
   injected as `DEEPSEEK_API_KEY` and `GEMINI_API_KEY`.
3. The LiteLLM config reads them via `os.environ/...` — the key material never
   appears in config, logs, or the repo.
4. Rotation = replace the env value and restart the container. One place.

## Failover test: "block DeepSeek, watch Gemini take over"

1. Start the gateway with a **bogus** `DEEPSEEK_API_KEY` but a real
   `GEMINI_API_KEY`.
2. Send a request to model group `workhorse`.
3. Expected: the first attempt fails against DeepSeek, LiteLLM falls back to
   `vision` (Gemini flash), and you still get a 200 with a completion.
4. Check the proxy logs — the fallback hop is recorded there.

This is the behaviour the whole substrate depends on: provider wobbles must be
invisible to the agents.

## After first boot

Create one virtual key per model group (LiteLLM UI at `:4000/ui` or the
key-generate API) with the per-group budgets from COSTS.md, and set 50%/80%
budget alerts. Agents then use their group's key instead of the master key —
spend is capped per group even if one agent goes wild.
