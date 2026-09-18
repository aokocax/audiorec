#!/usr/bin/env bash
# audiorec - profil icin tepe VRAM ve gecikme olcumu (Linux). TEST EDILMEDI (bench.py Windows'ta test edildi).
# Kullanim: ./bench.sh PROFIL SES_DOSYASI ["referans metin"] [SESSIZLIK_SANIYE]
#   Linux'ta yerlesik Turkce TTS yok: test sesini kendin ver (kamuya acik/sentetik Turkce ornek) ve isin sonunda sil.
#   Calisan sunucu varsa once ./stop.sh (bench kendi sunucusunu acar).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$ROOT"
PROFILE="${1:?profil}"; AUDIO="${2:?ses dosyasi}"; REF="${3:-}"; SIL="${4:-20}"
ARGS=(tools/bench.py --profile "$PROFILE" --audio "$AUDIO" --silence-seconds "$SIL")
[ -n "$REF" ] && ARGS+=(--ref-text "$REF")
exec .venv/bin/python "${ARGS[@]}"
