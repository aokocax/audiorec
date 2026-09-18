#!/usr/bin/env bash
# audiorec - arka plandaki sunucuyu durdur (Linux). TEST EDILMEDI.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$ROOT"
[ -f .run/server.pid ] || { echo "[stop] pid dosyasi yok"; exit 0; }
PID=$(cat .run/server.pid)
if kill -0 "$PID" 2>/dev/null; then kill "$PID"; sleep 2; kill -0 "$PID" 2>/dev/null && kill -9 "$PID"; echo "[stop] durduruldu (PID $PID)"; else echo "[stop] PID $PID zaten calismiyor"; fi
rm -f .run/server.pid
