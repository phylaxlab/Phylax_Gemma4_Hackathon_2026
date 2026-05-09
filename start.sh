#!/usr/bin/env bash
# Phylax local launcher: backend + frontend + Cloudflare Quick Tunnel.

set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CACHE="$ROOT/.cache"
BIN_DIR="$CACHE/bin"
LOG_DIR="$CACHE/logs"
VENV="$ROOT/.venv"

mkdir -p "$BIN_DIR" "$LOG_DIR"

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-${BACKEND_PORT:-8000}}"
API_URL_HOST="${API_URL_HOST:-$API_HOST}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
PHYLAX_TUNNEL="${PHYLAX_TUNNEL:-1}"
PHYLAX_TUNNEL_TOKEN="${PHYLAX_TUNNEL_TOKEN:-${CLOUDFLARED_TOKEN:-}}"
PHYLAX_PUBLIC_URL="${PHYLAX_PUBLIC_URL:-${PUBLIC_BASE_URL:-}}"

[ "$API_URL_HOST" = "0.0.0.0" ] && API_URL_HOST="127.0.0.1"

BACKEND_PID="$CACHE/backend.pid"
FRONTEND_PID="$CACHE/frontend.pid"
TUNNEL_PID="$CACHE/cloudflared.pid"
TUNNEL_URL_FILE="$CACHE/cloudflare-url.txt"

BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
TUNNEL_LOG="$LOG_DIR/cloudflared.log"

say() { printf '[Phylax] %s\n' "$*"; }
has() { command -v "$1" >/dev/null 2>&1; }
is_on() { case "${1:-}" in 1|true|TRUE|yes|YES|on|ON) return 0 ;; *) return 1 ;; esac; }

stop_pid() {
  local file="$1" name="$2" pid=""
  [ -f "$file" ] && pid="$(cat "$file" 2>/dev/null || true)"
  rm -f "$file"
  if [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then
    say "Stopping $name"
    kill "$pid" >/dev/null 2>&1 || true
  fi
}

clear_port() {
  local port="$1" pids=""
  has lsof || return 0
  pids="$(lsof -ti "tcp:$port" 2>/dev/null || true)"
  [ -z "$pids" ] || kill $pids >/dev/null 2>&1 || true
}

stop_all() {
  stop_pid "$TUNNEL_PID" "Cloudflare tunnel"
  stop_pid "$FRONTEND_PID" "frontend"
  stop_pid "$BACKEND_PID" "backend"
  rm -f "$TUNNEL_URL_FILE"
  clear_port "$FRONTEND_PORT"
  clear_port "$API_PORT"
}

reset_logs() {
  : > "$BACKEND_LOG"
  : > "$FRONTEND_LOG"
  : > "$TUNNEL_LOG"
}

python_cmd() {
  if has python3; then command -v python3; return 0; fi
  if has python; then command -v python; return 0; fi
  say "Python 3.9+ is required."
  exit 1
}

check_tools() {
  has npm || { say "Node.js/npm is required."; exit 1; }
  has ffmpeg || say "FFmpeg is not installed; camera export may be limited."
}

backend_python() {
  local py="$1"
  if [ ! -x "$VENV/bin/python" ]; then
    say "Creating .venv" >&2
    "$py" -m venv "$VENV"
  fi

  local vpy="$VENV/bin/python"
  if ! "$vpy" - <<'PYDEPS' >/dev/null 2>&1
import aiosqlite, cv2, fastapi, httpx, ollama, PIL, uvicorn
PYDEPS
  then
    say "Installing backend deps" >&2
    "$vpy" -m pip install --upgrade pip >&2
    "$vpy" -m pip install -r "$ROOT/server/requirements.txt" >&2
  fi
  printf '%s\n' "$vpy"
}

frontend_deps() {
  [ -d "$ROOT/frontend/node_modules" ] && return 0
  say "Installing frontend deps"
  if [ -f "$ROOT/frontend/package-lock.json" ]; then
    npm --prefix "$ROOT/frontend" ci
  else
    npm --prefix "$ROOT/frontend" install
  fi
}

wait_url() {
  local name="$1" url="$2"
  has curl || return 0
  for _ in $(seq 1 60); do
    curl -fsS "$url" >/dev/null 2>&1 && return 0
    sleep 0.5
  done
  say "$name did not answer yet. Check logs in $LOG_DIR."
}

start_backend() {
  local vpy="$1"
  say "Backend  http://$API_URL_HOST:$API_PORT"
  (cd "$ROOT/server" && API_HOST="$API_HOST" API_PORT="$API_PORT" "$vpy" main.py) >>"$BACKEND_LOG" 2>&1 &
  printf '%s\n' "$!" > "$BACKEND_PID"
}

start_frontend() {
  say "Frontend http://localhost:$FRONTEND_PORT"
  (cd "$ROOT/frontend" && npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT") >>"$FRONTEND_LOG" 2>&1 &
  printf '%s\n' "$!" > "$FRONTEND_PID"
}

cloudflared_bin() {
  if has cloudflared; then command -v cloudflared; return 0; fi

  local bin="$BIN_DIR/cloudflared"
  if [ -x "$bin" ]; then printf '%s\n' "$bin"; return 0; fi
  has curl || return 1

  local arch url
  arch="$(uname -m)"
  case "$arch" in
    x86_64|amd64) url="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64" ;;
    aarch64|arm64) url="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64" ;;
    *) return 1 ;;
  esac

  say "Downloading cloudflared" >&2
  curl -fsSL "$url" -o "$bin"
  chmod +x "$bin" 2>/dev/null || true
  printf '%s\n' "$bin"
}

start_tunnel() {
  is_on "$PHYLAX_TUNNEL" || return 0

  local cf
  if ! cf="$(cloudflared_bin)"; then
    say "Cloudflare tunnel skipped; install cloudflared or curl."
    return 0
  fi

  if [ -n "$PHYLAX_TUNNEL_TOKEN" ]; then
    say "Cloudflare Named Tunnel"
    "$cf" tunnel --no-autoupdate run --token "$PHYLAX_TUNNEL_TOKEN" >>"$TUNNEL_LOG" 2>&1 &
    printf '%s\n' "$!" > "$TUNNEL_PID"
    if [ -n "$PHYLAX_PUBLIC_URL" ]; then
      printf '%s\n' "$PHYLAX_PUBLIC_URL" > "$TUNNEL_URL_FILE"
      say "Public   $PHYLAX_PUBLIC_URL"
    else
      say "Public hostname is configured in Cloudflare."
    fi
    return 0
  fi

  say "Cloudflare Quick Tunnel"
  "$cf" tunnel --url "http://$FRONTEND_HOST:$FRONTEND_PORT" --no-autoupdate >>"$TUNNEL_LOG" 2>&1 &
  printf '%s\n' "$!" > "$TUNNEL_PID"

  for _ in $(seq 1 30); do
    local url=""
    url="$(grep -m1 -Eo 'https://[-a-zA-Z0-9.]+\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null || true)"
    if [ -n "$url" ]; then
      printf '%s\n' "$url" > "$TUNNEL_URL_FILE"
      say "Public   $url"
      return 0
    fi
    kill -0 "$(cat "$TUNNEL_PID")" >/dev/null 2>&1 || break
    sleep 1
  done

  say "Tunnel is starting; URL will appear in $TUNNEL_LOG."
}

print_summary() {
  local tunnel=""
  [ -f "$TUNNEL_URL_FILE" ] && tunnel="$(cat "$TUNNEL_URL_FILE")"

  cat <<EOF

Phylax is running
  Local:   http://localhost:$FRONTEND_PORT
  Backend: http://$API_URL_HOST:$API_PORT
EOF

  [ -z "$tunnel" ] || printf '  Public:  %s\n' "$tunnel"

  cat <<EOF

Logs: $LOG_DIR
Stop: bash start.sh stop
EOF
}

main() {
  trap stop_all INT TERM EXIT

  if [ "${1:-}" = "stop" ]; then
    stop_all
    exit 0
  fi

  stop_all
  reset_logs
  check_tools

  local vpy
  vpy="$(backend_python "$(python_cmd)")"

  frontend_deps
  start_backend "$vpy"
  wait_url "Backend" "http://$API_URL_HOST:$API_PORT/api/health"
  start_frontend
  wait_url "Frontend" "http://$FRONTEND_HOST:$FRONTEND_PORT"
  start_tunnel
  print_summary

  while true; do sleep 1; done
}

main "$@"
