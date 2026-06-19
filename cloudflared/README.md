# Cloudflare Tunnel (edge TLS)

The `cloudflared` service is gated behind the `edge` compose profile so local dev
runs without it. To expose the stack over the tunnel:

1. Create a tunnel in the Cloudflare Zero Trust dashboard and copy its token.
2. Put it in `.env` as `TUNNEL_TOKEN=...`.
3. Bring the stack up with the edge profile:
   `docker compose --profile edge up`

TLS terminates at the Cloudflare edge — there is no in-stack TLS proxy. The tunnel
also covers per-venue subdomains and on-demand custom-domain TLS (later phases).
