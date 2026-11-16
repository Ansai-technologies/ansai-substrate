# Hosting: Agent Office + Ansai Platform

Public URL: https://agents.ansaitechnologies.co.ke
  /          -> 3D agent office (office/static/index.html)
  /platform  -> Ansai Platform console (office/static/platform.html)

## Architecture

  browser -> Cloudflare Access (founder email only, one-time PIN)
          -> Cloudflare Tunnel "ansai-agents" (6b405f1f-51f9-40af-b034-daf1a04c0a68)
          -> cloudflared on the Lenovo (WSL2)
          -> FastAPI office server, localhost:8080 (office/server.py)
          -> LiteLLM gateway, localhost:4000 (gateway/, Docker)

The office is a Python + Docker stack, so it is NOT deployed to
Workers/Pages. The tunnel publishes the locally running server.
It is live only while the Lenovo, WSL, the office server and the
gateway are up.

## Security (non-negotiable)

office/server.py has no auth of its own and chat EXECUTES: council
seats get the worker tool profile (reads free; writes/shell/sends
gated by in-UI approval cards). Never run the tunnel without the
Cloudflare Access application in front of
agents.ansaitechnologies.co.ke allowing only the founder's email.
If Access is not enabled on the Cloudflare account, keep the tunnel
stopped.

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
