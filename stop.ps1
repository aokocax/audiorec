<#  audiorec - arka plandaki sunucuyu durdur (Windows)  #>
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $Root ".run\server.pid"
if (-not (Test-Path $pidFile)) { Write-Host "[stop] pid dosyasi yok; calisan sunucu bulunamadi"; exit 0 }
$id = Get-Content $pidFile
if (Get-Process -Id $id -ErrorAction SilentlyContinue) {
  taskkill /PID $id /T /F | Out-Null
  Write-Host "[stop] durduruldu (PID $id)"
} else {
  Write-Host "[stop] PID $id zaten calismiyor"
}
Remove-Item $pidFile -ErrorAction SilentlyContinue
