# Security Policy

## Supported Versions

| Version  | Supported          |
| -------- | ------------------ |
| 0.1.x    | :white_check_mark: |

Pre-0.1 builds, development snapshots, and `main`-branch checkouts are **not**
supported for security reports. Only the 0.1.x release line receives patches.

## Deployment Assumptions

firnline is designed for **LAN-only / trusted-network deployment**.
Key guardrails:

- **/mcp now bearer-gated** — the MCP server (`mcpd`) requires
  `MCPD_API_TOKEN` (validated via `secrets.compare_digest`). Unauthenticated
  requests receive 401.

- **WebUI auth is best-effort** — when `WEBUI_PASSWORD` is set the Reflex
  frontend gates all data pages behind a password form. When empty (default)
  all pages are open — intended for LAN-only use. **Do NOT expose port 3000
  directly to the internet.** Bind to loopback (`127.0.0.1:3000`) or place
  behind a reverse proxy with its own auth layer.

  Full webui event-auth and token hardening (random server secret, nonce,
  rate-limiting) is scoped for **0.2.0**.

- **Webhook allowlist fail-closed** — `WEBHOOK_ALLOWED_HOSTS` (comma-separated)
  restricts outbound webhook calls. If the list is **empty**, webhook execution
  is **refused** (fail-closed). The `Authorization: Bearer <default_token>`
  header is only attached when the target host is explicitly allowlisted.

- **CAPTURED_API_TOKEN** and **QUERYD_API_TOKEN** protect the REST surface.
  Generate strong tokens (`openssl rand -hex 32`) and never embed them in
  client-side code.

## Leaked-Key History

A bearer token was committed to the repository history **before the 0.1.0
release**. If you plan to share or publish a fork of this repository, you
**must** revoke that key and rewrite history (`git filter-repo`) to purge the
leak before making the repository public. The 0.1.0-alpha tag and all
subsequent commits are clean — only pre-0.1.0 history is affected.

## Reporting a Vulnerability

- **Preferred**: Open a [GitHub Security
  Advisory](https://github.com/BaLion29/lms/security/advisories) (private to
  maintainers).

- **Alternative**: Email the maintainers directly. We aim to acknowledge
  reports within 48 hours and provide a timeline for remediation.

Please include:
- A clear description of the vulnerability
- Steps to reproduce (minimal repro preferred)
- Whether you believe the issue is publicly known
- Any suggested fix (optional, appreciated)

We follow a 90-day coordinated disclosure schedule. Critical fixes are
released as patch versions on the supported release line.
