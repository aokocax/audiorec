#!/usr/bin/env bash
# audiorec - kurulum (Linux). NOT: Bu script Windows'ta gelistirildi, Linux'ta TEST EDILMEDI.
# Izole .venv + sabitlenmis surumler; admin gerektirmez (uv kullanici dizinine kurulur).
# Kullanim:  ./setup.sh [--diarization] [--no-lock]
#   --diarization : diart diarization bagimliliklarini da kur (pyannote modelleri icin HF token gerekir)
#   --no-lock     : lock yerine requirements*.in'den coz (yeni donanim/surum denemesi)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
PYVER="3.12"
# torch CUDA index'i: surucu >= 560 (CUDA 12.6+) icin cu126. Daha eski surucu: README "Yeni donanima tasima".
TORCH_IDX="${TORCH_IDX:-https://download.pytorch.org/whl/cu126}"
DIAR=0; NOLOCK=0
for a in "$@"; do case "$a" in --diarization) DIAR=1;; --no-lock) NOLOCK=1;; *) echo "bilinmeyen: $a"; exit 1;; esac; done

export UV_PYTHON_INSTALL_DIR="$ROOT/.python"   # Python proje icinde; sistem Python'una dokunmaz
export UV_LINK_MODE=copy

# 1) uv
if ! command -v uv >/dev/null 2>&1; then
  if [ ! -x "$HOME/.local/bin/uv" ]; then
    echo "[setup] uv kuruluyor (https://astral.sh/uv) ..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
  fi
  export PATH="$HOME/.local/bin:$PATH"
fi
uv --version

# 2) Python
uv python install "$PYVER" --no-bin

# 3) venv
[ -d .venv ] || uv venv --python "$PYVER" .venv

# 4) paketler (bkz. setup.ps1: diarization lock tam ortamdir, numpy 1.26)
if [ "$DIAR" = 1 ]; then
  if [ "$NOLOCK" = 1 ]; then REQS=(-r requirements.in -r requirements-diarization.in); else REQS=(-r requirements-diarization.lock); fi
else
  if [ "$NOLOCK" = 1 ]; then REQS=(-r requirements.in); else REQS=(-r requirements.lock); fi
fi
echo "[setup] kuruluyor: ${REQS[*]}  (torch index: $TORCH_IDX)"
uv pip install --python .venv --index-strategy unsafe-best-match --extra-index-url "$TORCH_IDX" "${REQS[@]}"

# 5) kontrol
.venv/bin/python tools/check_gpu.py --setup-check || echo "[setup] UYARI: torch CUDA gormuyor (surucu/CUDA uyumu icin README)"
# 6) varsayilan profilin modelini simdi indir (calisma zamani offline kalsin). Baska profil: tools/pull_models.py --profile AD
.venv/bin/python tools/pull_models.py
echo "[setup] tamam. Baslatmak icin: ./start.sh dev-6gb"
