# captured API

FastAPI capture-ingress daemon. Accepts notes and file uploads, dispatches
to pluggable `CaptureHandler` plugins by `kind`.

All endpoints except `/healthz` require bearer authentication.

## Authentication

**Bearer token** — `Authorization: Bearer <CAPTURED_API_TOKEN>`.

If the header is missing, malformed, or the token does not match
`CAPTURED_API_TOKEN`, a `401` response with `{"detail": "unauthorized"}`
is returned.

## Endpoints

### `GET /healthz`

Unauthenticated health check.

**Response `200`:**

```json
{
  "status": "ok",
  "terminusdb": "up",
  "version": "0.1.0",
  "modules": {"core": "0.1.0", "capture": "0.1.0", ...},
  "handlers": ["inbox_note", "inbox_audio"],
  "blob_root_writable": true
}
```

**Response `503`** when TerminusDB is unreachable:

```json
{
  "status": "degraded",
  "terminusdb": "down",
  "version": "0.1.0",
  "modules": {},
  "handlers": ["inbox_note"],
  "blob_root_writable": true
}
```

### `POST /v1/capture/note`

Submit a text capture. Requires bearer auth.

**Request body (JSON):**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `text` | string | yes | — | Text content to capture |
| `kind` | string | no | `"note"` | Semantic kind — dispatched to matching handler |
| `metadata` | object | no | `{}` | Arbitrary key-value metadata |
| `captured_at` | string (ISO 8601 with tz) | no | — | Capture timestamp |

**Response `201`:**

```json
{
  "id": "Captured/abc123",
  "kind": "note"
}
```

**Errors:**

| Status | Response | Condition |
|---|---|---|
| `401` | `{"detail": "unauthorized"}` | Missing or invalid token |
| `404` | `{"message": "...", "known_kinds": [...], "hint": "..."}` | No handler registered for `kind` |
| `422` | `{"message": "...", "hint": "..."}` | `kind` requires file upload (use `/v1/capture/file`) |
| `500` | `{"detail": "capture processing failed"}` | Handler raised an exception |

### `POST /v1/capture/file`

Submit a file capture (multipart form). Requires bearer auth.

**Form fields:**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `file` | file | yes | — | Uploaded file |
| `kind` | string | no | `"file"` | Semantic kind — dispatched to matching handler |
| `metadata` | string (JSON) | no | `"{}"` | JSON object with arbitrary metadata |
| `captured_at` | string (ISO 8601 with tz) | no | — | Capture timestamp |

**Response `201`:**

```json
{
  "id": "Captured/def456",
  "kind": "file",
  "sha256": "a1b2c3d4...",
  "size": 12345
}
```

**Errors:**

| Status | Response | Condition |
|---|---|---|
| `401` | `{"detail": "unauthorized"}` | Missing or invalid token |
| `413` | `{"detail": "upload exceeds maximum size of N bytes"}` | File exceeds `CAPTURED_MAX_UPLOAD_BYTES` |
| `422` | See conditions below | Various validation failures |
| `422` | `{"detail": "metadata must be valid JSON"}` | `metadata` is not valid JSON |
| `422` | `{"detail": "metadata must be a JSON object"}` | `metadata` is not a JSON object |
| `422` | `{"detail": "captured_at must be an ISO 8601 datetime with timezone"}` | `captured_at` invalid |
| `503` | `{"detail": "blob storage not configured (FIRNLINE_BLOB_ROOT is unset)"}` | Blob root not set |

## Design notes

- Handlers are plugin-based (`firnline.captured.handlers` entry-point group).
  Two built-in handlers ship with the `captured` service: `inbox_note` and
  `inbox_audio`.
- Collisions on `kind` across active plugins are fatal at startup.
- Upload size is capped by `CAPTURED_MAX_UPLOAD_BYTES` (default 50 MB).
- Content is stored in a content-addressed blob store at `FIRNLINE_BLOB_ROOT`.
- The handler's `handle()` method returns the created document IRI, which is
  forwarded in the response.

## Related documents

- [Configuration reference](../configuration.md)
- [Entry points reference](../entry-points.md)
- [API overview](README.md)
