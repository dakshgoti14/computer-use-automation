#!/usr/bin/env bash
# Starts the demo bank app (the automation target, internal-only) and then
# this system's own API (what the platform actually exposes) in the same
# container. Two separate uvicorn processes rather than mounting them as
# one ASGI app deliberately: the discovered capability artifact's
# start_url_template and safety-policy domain allowlist are already baked
# in as http://127.0.0.1:8001 - keeping the demo app a genuinely separate
# origin on that exact host:port means zero changes to the artifact or the
# safety policy to run this in a container.
set -euo pipefail

DEMO_APP_HOST="${DEMO_APP_HOST:-127.0.0.1}"
DEMO_APP_PORT="${DEMO_APP_PORT:-8001}"
API_PORT="${PORT:-8000}"

echo "[start.sh] launching demo bank app on ${DEMO_APP_HOST}:${DEMO_APP_PORT} (internal only) ..."
python -m uvicorn demo_app.app:app --host "$DEMO_APP_HOST" --port "$DEMO_APP_PORT" &
DEMO_PID=$!

# Fail fast and loudly if the demo app dies, rather than serving an API
# whose every replay will time out against a dead target.
trap 'kill -TERM "$DEMO_PID" 2>/dev/null || true' TERM INT

for _ in $(seq 1 30); do
  if curl -fsS "http://${DEMO_APP_HOST}:${DEMO_APP_PORT}/login" >/dev/null 2>&1; then
    echo "[start.sh] demo bank app is ready."
    break
  fi
  sleep 1
done

if ! kill -0 "$DEMO_PID" 2>/dev/null; then
  echo "[start.sh] demo bank app process died during startup - aborting." >&2
  exit 1
fi

echo "[start.sh] launching the integration API on 0.0.0.0:${API_PORT} ..."
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "$API_PORT"
