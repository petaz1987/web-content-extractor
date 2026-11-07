# Web Content Extractor — Coolify Deployment Runbook

This runbook prepares a private deployment from a GHCR image. It does not create a Coolify service, publish a port, configure a domain, or establish private networking.

## Before deployment

1. Select an approved `linux/arm64` GHCR image by immutable digest, for example `ghcr.io/petaz1987/web-content-extractor@sha256:<verified-digest>`. The digest must come from a completed approved publication workflow and match its source commit and image summary.
2. Configure the Compose service in Coolify with `compose.coolify.yaml` and set `WEB_CONTENT_EXTRACTOR_IMAGE` to that full digest reference.
3. Set the runtime values below. Configure `EXTRACT_API_TOKEN` separately using Coolify's protected secret interface; do not put the token in Git or an image.

```dotenv
PORT=5000
EXTRACT_CONNECT_TIMEOUT=10
EXTRACT_READ_TIMEOUT=20
EXTRACT_LOG_LEVEL=INFO
EXTRACT_MAX_CONCURRENT=1
```

4. The infrastructure team must arrange private service-to-service routing and firewall policy. The Compose file intentionally publishes no host port and defines no public domain or proxy route. The future internal URL is not specified here.

## Start and verify

1. Start the service and wait for the container healthcheck to report healthy. It calls unauthenticated `GET /health` over loopback inside the container.
2. Verify authentication from an approved private client: a request without a Bearer token should return 401; an authenticated `/health` request returns the existing health JSON.
3. Run an approved smoke extraction against a public test page. Confirm the response mode and semantic fields expected by the consumer. Do not use production credentials in shell history or logs.
4. Inspect Coolify logs and CPU/RAM use during one extraction before setting resource limits. Raspberry Pi 3B has limited RAM and CPU; extraction is intentionally serialized, and concurrent `/extract` requests receive HTTP 503 `extraction_busy` while one is running. `/health` remains available on the second WSGI thread.

## Timeouts and request lifecycle

- Upstream connect timeout limits a connection attempt; read timeout limits an individual upstream socket read. Defaults remain 5 and 10 seconds for native Render. The Coolify values above override them to 10 and 20 seconds. Multiple redirects and a peer that continues sending data can make total fetch duration exceed either number.
- Application parsing time has no separate hard deadline. The WSGI worker timeout is disabled (`--timeout 0`) so Gunicorn does not kill a valid long request based on an arbitrary wall-clock threshold. The client may have its own timeout; a client disconnect does not guarantee that server-side extraction work is cancelled.
- Gunicorn uses one worker and two threads: one extraction slot plus one thread for health/quick rejection. A busy extraction is rejected rather than queued. Gunicorn allows 30 seconds for graceful worker shutdown and Compose allows 35 seconds before force-kill; a host-level forced shutdown can still interrupt work.

## Rollback

Record the currently approved digest before changing the deployment. If health or smoke checks regress, redeploy the previous immutable digest and verify health/authentication again. Monitor CPU and memory before increasing concurrency or resource limits.

The existing native Render service at `https://extractwebsite.onrender.com` remains in service and unchanged until a separate cutover is approved.
