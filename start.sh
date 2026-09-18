#!/usr/bin/env bash
# audiorec - sunucuyu baslat (Linux). TEST EDILMEDI (Windows'ta gelistirildi).
# Kullanim: ./start.sh [PROFIL] [--force] [--foreground]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$ROOT"
PY="$ROOT/.venv/bin/python"; [ -x "$PY" ] || { echo "venv yok; once ./setup.sh"; exit 1; }
PROFILE=""; FORCE=""; FG=0
for a in "$@"; do case "$a" in --force) FORCE="--force";; --foreground) FG=1;; -*) echo "bilinmeyen: $a"; exit 1;; *) PROFILE="$a";; esac; done
ARGS=(server.py); [ -n "$PROFILE" ] && ARGS+=(--profile "$PROFILE"); [ -n "$FORCE" ] && ARGS+=("$FORCE")
if [ "$FG" = 1 ]; then exec "$PY" "${ARGS[@]}"; fi

mkdir -p .run
if [ -f .run/server.pid ] && kill -0 "$(cat .run/server.pid)" 2>/dev/null; then echo "[start] zaten calisiyor (PID $(cat .run/server.pid)); once ./stop.sh"; exit 0; fi
# VRAM/profil kontrolu gorunur olsun (otomatik dusurme yok)
CHK=(tools/check_gpu.py); [ -n "$PROFILE" ] && CHK+=(--profile "$PROFILE"); [ -n "$FORCE" ] && CHK+=("$FORCE")
"$PY" "${CHK[@]}" || { echo "[start] profil kontrolu gecmedi; baslatilmadi"; exit 2; }

nohup "$PY" "${ARGS[@]}" > .run/server.out.log 2> .run/server.log &
echo $! > .run/server.pid
echo "[start] PID $(cat .run/server.pid) - log: .run/server.log"
PORT=$(grep -E '^\s*port:' config.yaml | head -1 | sed -E 's/.*port:\s*([0-9]+).*/\1/'); PORT=${PORT:-8000}
HOST=$(grep -E '^\s*host:' config.yaml | head -1 | sed -E 's/.*host:\s*([0-9.]+).*/\1/'); HOST=${HOST:-127.0.0.1}
for i in $(seq 1 600); do
  kill -0 "$(cat .run/server.pid)" 2>/dev/null || { echo "[start] sunucu cikti. Log:"; tail -30 .run/server.log; exit 1; }
  curl -fs "http://$HOST:$PORT/health" >/dev/null 2>&1 && break
  sleep 1
done
echo "[start] hazir: http://$HOST:$PORT/   (durdurmak icin ./stop.sh)"
