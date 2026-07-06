#!/bin/sh
# ---------------------------------------------------------------------------
# firnline-ext entrypoint — installs extensions into an overlay directory,
# then execs the real entrypoint (CMD).
#
# Design:
#   - Bootstrap container: FIRNLINE_EXTENSIONS_INSTALL=true, installs wheels into
#     /opt/firnline-ext-venv/lib (--target), shared volume mounts this overlay.
#   - Service containers: FIRNLINE_EXTENSIONS_INSTALL=false (default), mounts the
#     same overlay read-only, only logs what is configured.
#
# Overlay mechanism:
#   pip install --target /opt/firnline-ext-venv/lib puts .dist-info directly into
#   the target.  With PYTHONPATH=/opt/firnline-ext-venv/lib, importlib.metadata
#   discovers entry points from those distributions.
#
# Dependencies: extensions' dependencies (firnline-core, structlog, …) are already
# present in the main /app/.venv.  We pass --no-deps because firnline-core is a
# workspace-local package that does not exist on PyPI.
# ---------------------------------------------------------------------------
set -eu

# --- constants ----------------------------------------------------------
OVERLAY_DIR="/opt/firnline-ext-venv"
OVERLAY_LIB="${OVERLAY_DIR}/lib"
LOCKFILE="${OVERLAY_DIR}/.lock"
LOG_PFX="[firnline-ext]"

# Use system Python's pip (the uv-built venv at /app/.venv/bin may lack pip).
# On python:3.12-slim-bookworm /usr/local/bin/python3 is the system python.
SYS_PYTHON="/usr/local/bin/python3"

# --- mode flags ---------------------------------------------------------
INSTALL_MODE="${FIRNLINE_EXTENSIONS_INSTALL:-false}"
PURGE_MODE="${FIRNLINE_EXTENSIONS_PURGE:-false}"
EXTENSIONS="${FIRNLINE_EXTENSIONS:-}"

# Trim leading/trailing whitespace
EXTENSIONS="$(echo "${EXTENSIONS}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"

if [ -z "${EXTENSIONS}" ]; then
    echo "${LOG_PFX} FIRNLINE_EXTENSIONS is empty or unset — nothing to do"
    exec "$@"
fi

echo "${LOG_PFX} configured extensions: ${EXTENSIONS}"

# -----------------------------------------------------------------------
# Verify-only mode (service containers with read-only overlay mount)
# -----------------------------------------------------------------------
if [ "${INSTALL_MODE}" != "true" ]; then
    echo "${LOG_PFX} install mode disabled (FIRNLINE_EXTENSIONS_INSTALL=${INSTALL_MODE})"
    echo "${LOG_PFX} extensions should already be installed in ${OVERLAY_LIB}"
    # Best-effort presence check for each extension
old_ifs="$IFS"
# Extension specs are comma-separated — they must NOT contain spaces because
# IFS=',' splitting treats the entire string between commas as one spec.
IFS=','
for raw in ${EXTENSIONS}; do
    spec="$(echo "${raw}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    [ -z "${spec}" ] && continue

    # Derive a distribution name from the spec for the check
        case "${spec}" in
            git+https://*|git+http://*)
                # Approximation: try to extract the package name from the URL
                dist_name="$(echo "${spec}" | sed 's|.*/||;s|\.git$||')"
                ;;
            *.whl)
                # Wheel filename: {name}-{version}-...whl
                # Strip version from first -<digit> so hyphenated names survive.
                dist_name="$(echo "${spec}" | sed 's|.*/||;s/-[0-9].*//' | tr '-' '_')"
                ;;
            *.tar.gz)
                dist_name="$(echo "${spec}" | sed 's|.*/||;s/\.tar\.gz$//;s/-[0-9].*//' | tr '-' '_')"
                ;;
            *)
                # PyPI name (strip version specifiers)
                dist_name="$(echo "${spec}" | sed 's/[<>=!].*//')"
                ;;
        esac

        dist_name_normalized="$(echo "${dist_name}" | tr '-' '_')"
        if [ -d "${OVERLAY_LIB}/${dist_name_normalized}" ] || \
           ls "${OVERLAY_LIB}/${dist_name_normalized}"-*.dist-info >/dev/null 2>&1; then
            echo "${LOG_PFX}   found: ${spec}  (${dist_name_normalized})"
        else
            echo "${LOG_PFX}   WARNING: ${spec} not found in overlay — extension may be missing"
        fi
    done
    IFS="${old_ifs}"
    exec "$@"
fi

# -----------------------------------------------------------------------
# Install mode (bootstrap container)
# -----------------------------------------------------------------------
echo "${LOG_PFX} install mode enabled — target: ${OVERLAY_LIB}"

mkdir -p "${OVERLAY_LIB}"

# --- purge -----------------------------------------------------------------
if [ "${PURGE_MODE}" = "true" ]; then
    echo "${LOG_PFX} purge mode: wiping ${OVERLAY_LIB}"
    find "${OVERLAY_LIB}" -mindepth 1 -delete
fi

# --- flock (best-effort) ----------------------------------------------------
LOCK_FD=9
if command -v flock >/dev/null 2>&1; then
    echo "${LOG_PFX} acquiring lock on ${LOCKFILE} ..."
    exec 9>"${LOCKFILE}"
    flock 9
    echo "${LOG_PFX} lock acquired"
fi

# --- install each extension -------------------------------------------------
install_one() {
    spec="$1"

    # Resolve the pip install argument
    case "${spec}" in
        git+https://*|git+http://*)
            install_arg="${spec}"
            ;;
        /*)
            # Absolute path
            install_arg="${spec}"
            ;;
        *.whl|*.tar.gz)
            # Relative wheel/tarball → resolve against /extensions
            install_arg="/extensions/${spec}"
            ;;
        *)
            # PyPI distribution name (possibly with version specifier)
            install_arg="${spec}"
            ;;
    esac

    echo "${LOG_PFX}   installing: ${install_arg}"
    # --no-deps: dependencies are already in the main /app/.venv.
    # firnline-core is not on PyPI, so full dep resolution would fail.
    # IMPORTANT: extensions must NOT share top-level module names — last
    # wheel installed wins (pip --target overwrites same-named files).
    ${SYS_PYTHON} -m pip install \
        --no-deps \
        --target "${OVERLAY_LIB}" \
        "${install_arg}"
}

old_ifs="$IFS"
# Extension specs must not contain spaces (IFS=',' splitting).
IFS=','
for raw in ${EXTENSIONS}; do
    spec="$(echo "${raw}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    [ -z "${spec}" ] && continue
    install_one "${spec}"
done
IFS="${old_ifs}"

# --- release lock -----------------------------------------------------------
if command -v flock >/dev/null 2>&1; then
    exec 9>&-
    echo "${LOG_PFX} lock released"
fi

echo "${LOG_PFX} installation complete"

exec "$@"
