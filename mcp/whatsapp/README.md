# WhatsApp MCP server — STUB

**Status: stub.** The tool contract (`send_message`, `read_messages`) is stable
and tested (`evals/test_tools.py`), but both bodies return marked stub payloads.
No real message is sent and nothing is fetched.

## Going live (later phase)

1. Create a WhatsApp Business Cloud API app (Meta developer dashboard),
   get `WHATSAPP_TOKEN` and `PHONE_NUMBER_ID`.
2. Replace the bodies in `server.py` per the inline TODOs:
   `POST /<PHONE_NUMBER_ID>/messages` for send, conversation GET for read.
3. Keep the return shapes — agents and evals depend on them.

## Cost note

From Oct 1, 2026 Meta bills in-window service messages per message (~KSh 0.52
in Kenya — verify current Meta pricing before launch). Design rule, already in
the stub's docstring: batch messages, be concise, resolve inside the 24h window.
The gateway's per-group spend caps do NOT cover Meta's messaging bill — track
it separately (see COSTS.md).
