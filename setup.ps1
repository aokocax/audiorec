<#
  audiorec - kurulum (Windows)
  Izole .venv + sabitlenmis surumler. Admin gerektirmez.
  Kullanim:  powershell -ExecutionPolicy Bypass -File setup.ps1 [-Diarization] [-NoLock]
    -Diarization : diart diarization bagimliliklarini da kur (pyannote modelleri icin HF token gerekir)
    -NoLock      : requirements.lock yerine requirements.in'den coz (yeni donanim/yeni surum denemesi icin)
#>
param([switch]$Diarization, [switch]$NoLock)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$PyVer   = "3.12"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Root ".python"   # Python da proje icinde: tasinabilir, sistemden bagimsiz
$env:UV_LINK_MODE = "copy"
$TorchIdx = "https://download.pytorch.org/whl/cu126"   # surucu >= 560 / CUDA 12.6+ icin. Yeni makinede README'ye bak.

# 1) uv (paket/Python yoneticisi) - kullanici dizinine kurulur
$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
  $cand = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
  if (-not (Test-Path $cand)) {
    Write-Host "[setup] uv bulunamadi, kuruluyor (https://astral.sh/uv)..."
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
  }
  $env:PATH = (Join-Path $env:USERPROFILE ".local\bin") + ";" + $env:PATH
}
uv --version

# 2) Python 3.12 (uv indirir, .python/ altina koyar; sistem Python'una dokunmaz)
uv python install $PyVer --no-bin

# 3) venv
if (-not (Test-Path ".venv")) { uv venv --python $PyVer .venv }

# 4) Paketler
#    requirements.lock              : temel ortam (numpy 2.x)
#    requirements-diarization.lock  : temel + diart diarization (numpy 1.26; diart numpy<2 ister). TAM ortamdir,
#                                     temel lock'un ustune degil onun yerine kurulur.
if ($Diarization) {
  $reqs = if ($NoLock) { @("requirements.in", "requirements-diarization.in") } else { @("requirements-diarization.lock") }
} else {
  $reqs = if ($NoLock) { @("requirements.in") } else { @("requirements.lock") }
}
Write-Host "[setup] kuruluyor: $reqs  (torch index: $TorchIdx)"
$reqArgs = @(); foreach ($r in $reqs) { $reqArgs += "-r"; $reqArgs += $r }
uv pip install --python .venv --index-strategy unsafe-best-match --extra-index-url $TorchIdx @reqArgs

# 5) Hizli kontrol
& .venv\Scripts\python.exe tools\check_gpu.py --setup-check

# 6) Varsayilan profilin modelini simdi indir (calisma zamani offline kalsin). Baska profil: tools\pull_models.py --profile AD
& .venv\Scripts\python.exe tools\pull_models.py
Write-Host "[setup] tamam. Baslatmak icin:  .\start.ps1 -Profile dev-6gb"
