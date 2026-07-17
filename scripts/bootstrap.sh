#!/bin/sh
set -eu

# ---------------------------------------------------------------------------
# Firnline bootstrap — waits for TerminusDB, creates the database if needed,
# then composes, applies, and validates the schema.
#
# This script is the default CMD of the firnline-schema image.
# The entrypoint (docker/entrypoint.sh) installs extensions first, then execs
# this script.  Environment variables:
#
#   TDB_URL         TerminusDB base URL (default: http://terminusdb:6363)
#   TDB_ORG         TerminusDB organisation (default: admin)
#   TDB_DB          TerminusDB database name (default: firnline)
#   TDB_USER        TerminusDB user (default: admin)
#   TDB_BRANCH      TerminusDB branch (default: main)
#   FIRNLINE_SCHEMA_TDB_PASSWORD  TerminusDB password (REQUIRED)
#   SCHEMA_MODULES_DIR  Path to schema modules (default: /app/schema/modules)
#   BUILD_OUT_DIR   Path for composed schema output (default: /tmp/build)
# ---------------------------------------------------------------------------

TDB_URL="${TDB_URL:-http://terminusdb:6363}"
TDB_ORG="${TDB_ORG:-admin}"
TDB_DB="${TDB_DB:-firnline}"
TDB_USER="${TDB_USER:-admin}"
TDB_BRANCH="${TDB_BRANCH:-main}"
SCHEMA_MODULES_DIR="${SCHEMA_MODULES_DIR:-/app/schema/modules}"
BUILD_OUT_DIR="${BUILD_OUT_DIR:-/tmp/build}"

# ---------------------------------------------------------------------------
# 1. Wait for TerminusDB
# ---------------------------------------------------------------------------
echo "=== Waiting for TerminusDB ==="
python << "PYEOF"
import httpx, os, sys, time
tdb_url = os.environ.get('TDB_URL', 'http://terminusdb:6363')
deadline = time.monotonic() + 120
while time.monotonic() < deadline:
    try:
        r = httpx.get(f'{tdb_url}/api/info', timeout=5)
        if r.status_code < 500:
            print(' TerminusDB is ready.')
            break
    except Exception:
        pass
    print('.', end='', flush=True)
    time.sleep(3)
else:
    sys.exit(f'TerminusDB not reachable at {tdb_url} after 120s — is the bundled terminusdb service running, or is TDB_URL correct?')
PYEOF

# ---------------------------------------------------------------------------
# 2. Ensure the database exists
# ---------------------------------------------------------------------------
echo "=== Ensure database exists ==="
python << "PYEOF"
import asyncio, os, sys
from firnline_core.tdb import TdbClient
async def main():
    async with TdbClient(
        base_url=os.environ.get("TDB_URL", "http://terminusdb:6363"),
        org=os.environ.get("TDB_ORG", "admin"),
        db=os.environ.get("TDB_DB", "firnline"),
        user=os.environ.get("TDB_USER", "admin"),
        password=os.environ["FIRNLINE_SCHEMA_TDB_PASSWORD"],
        author="service:ingestd",
    ) as c:
        if await c.db_exists():
            print("Database already exists.")
        else:
            await c.create_db()
            print("Database created.")
asyncio.run(main())
PYEOF

# ---------------------------------------------------------------------------
# 3. Compose schema
# ---------------------------------------------------------------------------
echo "=== Compose schema ==="
firnline-schema compose --modules-dir "$SCHEMA_MODULES_DIR" --out-dir "$BUILD_OUT_DIR"

# ---------------------------------------------------------------------------
# 4. Apply schema + migrations
# ---------------------------------------------------------------------------
echo "=== Apply schema ==="
firnline-schema apply --modules-dir "$SCHEMA_MODULES_DIR" \
  --tdb-url "$TDB_URL" \
  --tdb-org "$TDB_ORG" \
  --tdb-db "$TDB_DB" \
  --tdb-user "$TDB_USER" \
  --branch "$TDB_BRANCH"

# ---------------------------------------------------------------------------
# 5. Validate
# ---------------------------------------------------------------------------
echo "=== Validate ==="
firnline-schema validate --modules-dir "$SCHEMA_MODULES_DIR" \
  --tdb-url "$TDB_URL" \
  --tdb-org "$TDB_ORG" \
  --tdb-db "$TDB_DB" \
  --tdb-user "$TDB_USER" \
  --branch "$TDB_BRANCH"

echo "=== Bootstrap complete ==="
