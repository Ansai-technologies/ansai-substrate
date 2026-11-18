# Hosting: Agent Office + Ansai Platform

Public URL: https://agents.ansaitechnologies.co.ke
  /          -> 3D agent office (office/static/index.html)
  /platform  -> Ansai Platform console (office/static/platform.html)

## Architecture

  browser -> Ansai ID sign-in (enforced in office/server.py itself)
          -> Cloudflare Tunnel "ansai-agents" (6b405f1f-51f9-40af-b034-daf1a04c0a68)
          -> cloudflared on the Lenovo (WSL2)
          -> FastAPI office server, localhost:8080 (office/server.py)
          -> LiteLLM gateway, localhost:4000 (gateway/, Docker)

The office is a Python + Docker stack, so it is NOT deployed to
Workers/Pages. The tunnel publishes the locally running server.
It is live only while the Lenovo, WSL, the office server and the
gateway are up.

## Security (non-negotiable)

office/server.py enforces Ansai ID sign-in itself (the gate below
the app definition): every route except /api/health and
/events/ingest requires a live ansai_id_session, verified against
id.ansaitechnologies.co.ke/session, failing closed. Chat EXECUTES -
council seats get the worker tool profile (reads free; writes/shell/
sends gated by in-UI approval cards) - so the gate is what makes it
safe to leave the tunnel up. Never run the tunnel with
OFFICE_ID_GATE=off. A Cloudflare Access application in front of the
hostname remains welcome as a second layer, but it is no longer the
only lock.

Known open edge: POST /events/ingest accepts display events without
a session, because emitters on this machine hold no browser cookie.
It runs no tools and moves no money; the worst case is a forged
event on the 3D floor. Harden it before ingest ever carries more
than display data.

Never commit tunnel credentials: ~/.cloudflared/<tunnel-id>.json and
~/.cloudflared/cert.pem stay on the machine only. config.yml in this
folder contains no secret (the tunnel ID is public in DNS).

## Run / stop

  cp deploy/cloudflared/config.yml ~/.cloudflared/config.yml
  cloudflared tunnel run ansai-agents

Stop by killing cloudflared; the hostname then returns Cloudflare
530 while localhost:8080 keeps working.

DNS: agents.ansaitechnologies.co.ke is a proxied CNAME to
6b405f1f-51f9-40af-b034-daf1a04c0a68.cfargotunnel.com, created by:

  cloudflared tunnel route dns ansai-agents agents.ansaitechnologies.co.ke
