# Web Content Extractor

Web Content Extractor is a lightweight Flask API that retrieves public HTML pages and extracts bounded content for downstream tools such as Morpheus. It does not run a browser, execute JavaScript, or call an LLM. Repository: [github.com/petaz1987/web-content-extractor](https://github.com/petaz1987/web-content-extractor).

## API

All `/extract` requests require `Authorization: Bearer <EXTRACT_API_TOKEN>`. The token is required at application startup and is never logged or returned.

### Health

`GET /health` is unauthenticated and makes no network request:

```json
{"status":"ok","service":"extractwebsite"}
```

The `service` value is a legacy machine-readable identifier retained for compatibility. The current Render URL also retains the original repository name: `https://extractwebsite.onrender.com`.

### Full extraction (default)

`GET /extract?url=<url>` returns the established full response: `url` (final URL after redirects), `requested_url`, `title`, `meta_description`, `main_text`, `links`, `raw_html`, `content_type`, `status_code`, `content_status`, `usable`, and `block_reason`. Text, raw HTML and link inventory are bounded; the main text is capped at 50,000 characters, raw HTML at 100,000 characters, and links at 100 entries.

### Agent extraction

`GET /extract?url=<url>&mode=agent` returns a compact response with `url`, `requested_url`, `title`, `meta_description`, `main_text`, `content_type`, `status_code`, `content_status`, `usable`, and `block_reason`. It omits raw HTML and links by default. Add `include_links=1` to include the bounded link inventory. Returned links are untrusted page data; validate them before making another request.

Full mode uses Trafilatura with a BeautifulSoup fallback. Agent mode uses a separate deterministic reduction path with bounded semantic hints and structured data; it does not run an LLM, browser, or JavaScript. Agent `main_text` is capped at 35,000 characters.

### Search extraction

`GET /extract?url=<search-page-url>&mode=search` returns the existing six-field search response: `mode`, `extraction_status`, `source_url`, `product_count`, `products`, and `truncated`. Search mode currently supports the isolated IKEA search parser, with up to 20 records. `product_count` counts returned products. `truncated` is true when the output limit was reached and additional identifiable products remain. `ok` means products were extracted without reaching the output limit; `partial` means identifiable records could not all be parsed or the output limit was reached; `no_products` means usable content had no recognized products; `unusable` means blocked or empty page content. It does not verify stock or fetch product detail pages.

### Product extraction

`GET /extract?url=<product-page-url>&mode=product` returns the existing five top-level fields: `mode`, `extraction_status`, `source_url`, `product`, and `warnings`. The product object contains `name`, `sku`, `brand`, `price`, `original_price`, `currency`, `variant`, `url`, `image_url`, `availability_evidence`, `details_markdown`, and `technical_details_markdown`. Generic evidence parsing and isolated Guanxe enrichment are implemented; IKEA product fixtures remain covered by the regression suite. `ok` requires reliably associated product identity and current price/currency; `partial` reports missing or conflicting core evidence; `no_product` means no reliable main product was identified; and `unusable` means the page was blocked or empty. Markdown output is bounded to 40,000 characters per field and 60,000 combined. Visible availability text is evidence only and does not establish inventory.

`include_links` is supported only with agent mode. Duplicate or unsupported query parameters are rejected with HTTP 400.

Example authenticated request (set the token in the environment first):

```sh
curl --get 'http://127.0.0.1:5000/extract' \
  --data-urlencode 'url=https://example.com/' \
  --data-urlencode 'mode=agent' \
  -H "Authorization: Bearer ${EXTRACT_API_TOKEN}"
```

### Content assessment and errors

HTTP 2xx from the upstream site means the fetch succeeded at the transport layer. `content_status` is `ok`, `blocked`, or `empty`; `usable` is true only for `ok`. A detected challenge reports `blocked` / `false` / `anti_bot_challenge`. Missing or whitespace-only main text reports `empty` / `false` / `null`. HTTP status remains separate from semantic usability. Do not treat `usable: false` content as verified page evidence.

Errors use a safe JSON shape, such as `{"error":{"code":"unsafe_url","message":"The requested URL is not allowed."}}`. Typical statuses: 400 invalid input, 401 authentication, 403 unsafe target, 413 oversized upstream body, 415 unsupported content, 502 fetch/redirect failure, 503 `extraction_busy`, and 504 upstream timeout. A single extraction runs at a time in the container; additional extraction requests are rejected immediately rather than queued. `/health` remains available on the second WSGI thread.

## Security boundaries and limits

- Only HTTP and HTTPS targets are accepted. URL credentials are rejected. Local, private, loopback, link-local, reserved and non-global DNS/IP targets are blocked for IPv4 and IPv6.
- DNS answers are checked before each request and redirect; redirects are followed manually and revalidated, up to five. Requests performs its own DNS resolution while connecting, so DNS rebinding between validation and connection remains a residual TOCTOU risk. This implementation does not claim to eliminate it.
- Fetches use a fresh Requests session with environment proxies disabled, no caller headers/cookies, and an identity-only encoding policy. Only HTML/XHTML is accepted and streamed response bytes are capped at 5 MiB.
- Legacy defaults remain a 5-second connect timeout and 10-second read timeout. These limit individual upstream connection/read operations, not the total time across redirects or all page parsing. A peer that keeps sending data may make total duration longer. There is no separate hard application deadline.
- The existing outbound User-Agent is retained because changing it could affect retailer access behavior: `ExtractWebsite/1.0 (+https://github.com/petaz1987/extractwebsite)`. It identifies the former repository but is not a project branding field.
- Logs include safe request categories, status, timings and byte counts. They do not include target URLs, query strings, page content, tokens or arbitrary upstream exception messages. DEBUG does not enable Flask's interactive debugger or verbose Requests/urllib3 logs.

## Runtime configuration

| Variable | Default | Validation and purpose |
|---|---:|---|
| `EXTRACT_API_TOKEN` | required | Bearer authentication secret |
| `PORT` | `5000` | Integer from 1 through 65535 |
| `EXTRACT_CONNECT_TIMEOUT` | `5` | Number from 0.1 through 120 seconds |
| `EXTRACT_READ_TIMEOUT` | `10` | Number from 0.1 through 120 seconds |
| `EXTRACT_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` |
| `EXTRACT_MAX_CONCURRENT` | `0` (unlimited) | `0` for native default or `1` for a single guarded extraction; container sets `1` |

Invalid explicit values fail startup with a sanitized diagnostic. Native Render defaults and commands remain compatible: `pip install -r requirements.txt`, then `python main.py`. Container-only Gunicorn is isolated in `requirements-container.txt`; `requirements.txt` is unchanged.

## Local development

Python 3.10 or newer is supported by the application dependencies.

```sh
python -m venv .venv
# Activate the environment, then install development dependencies.
pip install -r requirements-dev.txt
```

PowerShell:

```powershell
$env:EXTRACT_API_TOKEN = 'local-development-token'
python main.py
```

Run the offline tests with `python -m pytest`. The test suite mocks DNS and HTTP and does not call public sites.

## Native Render deployment

Continue using the existing Render service at `https://extractwebsite.onrender.com`. Keep the native Python build command `pip install -r requirements.txt` and start command `python main.py`. Configure `EXTRACT_API_TOKEN` in Render's environment. Docker is optional and is not required for Render. No Render configuration or deployment change is part of this repository update.

## ARM64 Docker image

`Dockerfile` builds and tests a non-root `linux/arm64` image. The build uses a builder/test stage so compiler and test-only dependencies are not copied into the runtime image. The runtime uses Gunicorn with one process, two WSGI threads, and one guarded extraction slot. The WSGI timeout is disabled to avoid killing a legitimate slow extraction; connect/read limits are per network operation, not a total request deadline. The second thread can serve health and reject busy extraction requests. SIGTERM is handled by Gunicorn; graceful shutdown waits up to 30 seconds.

Container dependencies are isolated in `requirements-container.txt` and do not affect Render. The image healthcheck calls `/health` over container loopback. `EXPOSE 5000` is image metadata only; the Coolify Compose file has no `ports:` mapping.

Build and run locally on an ARM64 host:

```sh
docker build --platform linux/arm64 -t web-content-extractor:local .
docker run --rm --stop-timeout 35 -e EXTRACT_API_TOKEN='local-token' -p 127.0.0.1:5000:5000 web-content-extractor:local
```

The repository's GitHub Actions workflow uses QEMU/Buildx to build ARM64 off the Raspberry Pi, checks architecture, runs native and in-image tests, and checks startup, health, auth, configuration, modes and SSRF behavior. An optional manually requested public DNS/HTTPS smoke test is separate and non-gating.

## GHCR release and Coolify

The image name is `ghcr.io/petaz1987/web-content-extractor`. Branch and pull-request validation cannot publish. An explicit manual workflow dispatch on `main` with `publish=true`, followed by approval through the protected `ghcr-publish` GitHub Environment, is required. Configure environment reviewers and restrictions in GitHub repository settings before using publication. The publication job reuses the exact ARM64 image tar that passed validation and records the source SHA, image ID, architecture, and actual registry digest. No image has been published by this local change, so no digest is provided here.

Coolify uses `compose.coolify.yaml`, which requires `WEB_CONTENT_EXTRACTOR_IMAGE` to be an immutable GHCR `@sha256:` reference. Illustrative format only, not a real digest: `ghcr.io/petaz1987/web-content-extractor@sha256:<placeholder-digest>`. Replace the placeholder with the digest from an approved publication. It publishes no host port and creates no public domain or Traefik route. Configure private routing and firewall policy separately; the internal URL is intentionally unspecified.

Approved initial Coolify runtime values are:

```dotenv
PORT=5000
EXTRACT_CONNECT_TIMEOUT=10
EXTRACT_READ_TIMEOUT=20
EXTRACT_LOG_LEVEL=INFO
```

Configure `EXTRACT_API_TOKEN` separately as a protected runtime secret. The 10/20 values are Coolify deployment settings only and do not change native Render defaults. See [the Coolify deployment runbook](docs/coolify-deployment.md) for digest checks, private networking prerequisites, smoke tests, resource monitoring and rollback.

The container assumes outbound DNS and HTTP/HTTPS access to public targets and a standard Docker network. It does not require a fixed n8n server, host address, SSH tunnel, VPN, internal DNS name, or browser runtime. No Coolify or Raspberry Pi deployment has been performed or verified as part of this change.
