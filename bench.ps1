<#
  audiorec - profil icin tepe VRAM ve gecikme olcumu (Windows)
  Kullanim:  .\bench.ps1 -Profile dev-6gb [-Audio test.wav] [-RefText "..."] [-SilenceSeconds 20] [-Force]
    -Audio yoksa Windows'un Turkce sesiyle (Tolga) gecici bir test sesi uretir ve bitince siler.
  Sonuc: bench-results\<profil>-<zaman>.json  (ses icermez)
  Calisan bir sunucu varsa once .\stop.ps1 (bench kendi sunucusunu acar; port cakisir).
#>
param([string]$Profile = "", [string]$Audio = "", [string]$RefText = "", [double]$SilenceSeconds = 20, [switch]$Force)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$py = Join-Path $Root ".venv\Scripts\python.exe"
$tmpAudio = ""
if (-not $Audio) {
  $tmpAudio = Join-Path $env:TEMP ("audiorec-bench-" + [guid]::NewGuid().ToString("N") + ".wav")
  $RefText = & (Join-Path $Root "tools\make_test_audio.ps1") -Out $tmpAudio
  $Audio = $tmpAudio
}
$args_ = @("tools\bench.py", "--audio", $Audio, "--silence-seconds", $SilenceSeconds)
if ($Profile) { $args_ += @("--profile", $Profile) }
if ($RefText) { $args_ += @("--ref-text", $RefText) }
if ($Force)   { $args_ += "--force" }
try {
  & $py @args_
} finally {
  if ($tmpAudio -and (Test-Path $tmpAudio)) { Remove-Item $tmpAudio -Force; Write-Host "[bench] gecici test sesi silindi" }
}
