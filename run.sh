#!/bin/sh
# Marswalk Planner - one-command start for macOS and Linux.
#
# What it does: finds Python 3.10+, creates .venv on the first run, installs
# requirements.txt (again only when it changed), starts the planner and opens
# it in your browser.
#
# Usage:
#   ./run.sh                     start on port 8000
#   ./run.sh 8001                start on port 8001
#   ./run.sh --reload            restart the server when code changes
#   ./run.sh 8001 --no-browser
#
# Flags:
#   PORT          a number sets the port (default 8000, or env PORT)
#   --reload      passed to uvicorn, for developers
#   --no-browser  do not open the browser
#   --help        show this help
#
# Environment variables:
#   PORT             port to use when none is given on the command line
#   MARSWALK_PYTHON  path to an existing python that already has the
#                    requirements; skips .venv and installs (CI / testing)
#
# Stop the server with Ctrl+C.

set -eu
cd "$(dirname "$0")"

usage() {
    echo "Usage: ./run.sh [PORT] [--reload] [--no-browser]"
    echo "  PORT          port to serve on (default 8000, or env PORT)"
    echo "  --reload      restart the server when code changes"
    echo "  --no-browser  do not open the browser"
    echo "Env: PORT, MARSWALK_PYTHON (use this python, skip .venv)"
}

die() {
    echo "Error: $*" >&2
    exit 1
}

PORT="${PORT:-8000}"
RELOAD=""
NOBROWSER=""
for arg in "$@"; do
    case "$arg" in
        --reload) RELOAD="--reload" ;;
        --no-browser) NOBROWSER=1 ;;
        -h|--help) usage; exit 0 ;;
        *) PORT="$arg" ;;
    esac
done

case "$PORT" in
    ''|*[!0-9]*) die "\"$PORT\" is not a valid port. Use a number from 1 to 65535, e.g. ./run.sh 8001" ;;
esac
if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
    die "\"$PORT\" is not a valid port. Use a number from 1 to 65535, e.g. ./run.sh 8001"
fi

# ---- pick the Python to use ----
VERSION_OK='import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)'

if [ -n "${MARSWALK_PYTHON:-}" ]; then
    PY="$MARSWALK_PYTHON"
    [ -x "$PY" ] || command -v "$PY" >/dev/null 2>&1 || die "MARSWALK_PYTHON points to \"$PY\", which does not exist."
    echo "Using MARSWALK_PYTHON=$PY (no .venv, no installs)"
    "$PY" -c 'import fastapi, uvicorn' >/dev/null 2>&1 || \
        die "MARSWALK_PYTHON cannot import fastapi and uvicorn. Install them first: \"$PY\" -m pip install -r requirements.txt"
else
    PY=".venv/bin/python"
    if [ ! -x "$PY" ]; then
        PYBASE=""
        for cand in python3.12 python3 python; do
            if command -v "$cand" >/dev/null 2>&1 && "$cand" -c "$VERSION_OK" >/dev/null 2>&1; then
                PYBASE="$cand"
                break
            fi
        done
        if [ -z "$PYBASE" ]; then
            echo "Error: Python 3.10 or newer was not found (tried python3.12, python3, python)." >&2
            echo "  Install it from https://www.python.org/downloads/ (or your package manager), then run this again." >&2
            exit 1
        fi
        echo "Creating .venv with: $PYBASE"
        if ! "$PYBASE" -m venv .venv; then
            echo "Error: could not create .venv with $PYBASE." >&2
            echo "  On Debian/Ubuntu install the venv module first: sudo apt install python3-venv" >&2
            rm -rf .venv
            exit 1
        fi
    fi
    "$PY" -c 'import sys' >/dev/null 2>&1 || \
        die ".venv exists but its Python does not start (was Python moved or removed?). Delete the .venv folder and run this again."

    # ---- install requirements only when requirements.txt changed ----
    if ! "$PY" -c "import hashlib,os,sys;h=hashlib.sha256(open('requirements.txt','rb').read()).hexdigest();s=os.path.join('.venv','.requirements.sha256');sys.exit(0 if os.path.isfile(s) and open(s).read().strip()==h else 1)"; then
        echo "Installing dependencies (the first run can take a few minutes)..."
        "$PY" -m pip install --upgrade pip --quiet --disable-pip-version-check || true
        if ! "$PY" -m pip install --disable-pip-version-check -r requirements.txt; then
            echo
            echo "Full install failed. Retrying without rasterio..."
            REQTMP="$(mktemp "${TMPDIR:-/tmp}/marswalk-req.XXXXXX")"
            "$PY" -c "import re,sys;open(sys.argv[1],'w').writelines(l for l in open('requirements.txt') if not re.match(r'\s*rasterio\b',l,re.I))" "$REQTMP"
            if ! "$PY" -m pip install --disable-pip-version-check -r "$REQTMP"; then
                rm -f "$REQTMP"
                die "installing dependencies failed. Check your internet connection and the messages above."
            fi
            rm -f "$REQTMP"
            echo "Note: installed without rasterio; it is only needed to rebuild map data (build_cube.py)."
        fi
        "$PY" -c "import hashlib,os;open(os.path.join('.venv','.requirements.sha256'),'w').write(hashlib.sha256(open('requirements.txt','rb').read()).hexdigest())"
    fi
fi

# ---- check the port ----
port_busy() {
    if command -v lsof >/dev/null 2>&1; then
        lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
    else
        "$PY" -c "import socket,sys;s=socket.socket();s.settimeout(0.3);sys.exit(0 if s.connect_ex(('127.0.0.1',int(sys.argv[1])))==0 else 1)" "$1"
    fi
}

if port_busy "$PORT"; then
    SUGGEST=$((PORT + 1))
    while [ "$SUGGEST" -le 65535 ] && [ "$SUGGEST" -lt $((PORT + 50)) ] && port_busy "$SUGGEST"; do
        SUGGEST=$((SUGGEST + 1))
    done
    echo "Error: port $PORT is already in use (maybe the planner is already running?)." >&2
    echo "  Try another port:     ./run.sh $SUGGEST" >&2
    if command -v lsof >/dev/null 2>&1; then
        echo "  See what is using it: lsof -i :$PORT" >&2
    fi
    exit 1
fi

echo
echo "  Marswalk Planner"
echo "  Planner:   http://localhost:$PORT/"
echo "  Gear page: http://localhost:$PORT/kit.html"
echo "  Stop:      press Ctrl+C"
echo

# ---- open the browser once /api/regions answers ----
POLLER=""
if [ -z "$NOBROWSER" ]; then
    OPENER=""
    if command -v open >/dev/null 2>&1 && [ "$(uname -s)" = "Darwin" ]; then
        OPENER="open"
    elif command -v xdg-open >/dev/null 2>&1; then
        OPENER="xdg-open"
    fi
    if [ -n "$OPENER" ]; then
        (
            i=0
            while [ "$i" -lt 120 ]; do
                if "$PY" -c "import sys,urllib.request as r;r.build_opener(r.ProxyHandler({})).open(sys.argv[1],timeout=2)" "http://127.0.0.1:$PORT/api/regions" >/dev/null 2>&1; then
                    "$OPENER" "http://localhost:$PORT/" >/dev/null 2>&1 || true
                    exit 0
                fi
                sleep 1
                i=$((i + 1))
            done
        ) &
        POLLER=$!
    fi
fi

cleanup() {
    if [ -n "$POLLER" ]; then
        kill "$POLLER" 2>/dev/null || true
    fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM

STATUS=0
# shellcheck disable=SC2086  # $RELOAD is empty or a single flag
"$PY" -m uvicorn gear_server:server --host 127.0.0.1 --port "$PORT" $RELOAD || STATUS=$?
exit "$STATUS"
