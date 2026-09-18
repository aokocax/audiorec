<#
  audiorec - sunucuyu baslat (Windows)
  Kullanim:  .\start.ps1 [-Profile dev-6gb] [-Force] [-Foreground]
    -Profile     config.yaml icindeki profil adi (varsayilan: config.yaml 'profile')
    -Force       VRAM kontrolu "sigmiyor" dese de baslat
    -Foreground  arka plana atma, bu pencerede calistir (Ctrl+C ile durur)
  Arka planda: PID .run\server.pid, log .run\server.log (log seviyesi config'ten; WARNING'de transkript loga dusmez)
#>
param([string]$Profile = "", [switch]$Force, [switch]$Foreground)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Error "venv yok. Once .\setup.ps1 calistir."; exit 1 }

$args_ = @("server.py")
if ($Profile) { $args_ += @("--profile", $Profile) }
if ($Force)   { $args_ += "--force" }

if ($Foreground) {
  & $py @args_
  exit $LASTEXITCODE
}

New-Item -ItemType Directory -Force (Join-Path $Root ".run") | Out-Null
$pidFile = Join-Path $Root ".run\server.pid"
if (Test-Path $pidFile) {
  $old = Get-Content $pidFile
  if (Get-Process -Id $old -ErrorAction SilentlyContinue) { Write-Host "[start] zaten calisiyor (PID $old). Once .\stop.ps1"; exit 0 }
}
# once VRAM/profil kontrolu gorunur sekilde calissin (otomatik dusurme yok; sigmiyorsa burada durur)
$chk = @("tools\check_gpu.py"); if ($Profile) { $chk += @("--profile", $Profile) }; if ($Force) { $chk += "--force" }
& $py @chk
if ($LASTEXITCODE -ne 0) { Write-Host "[start] profil kontrolu gecmedi (kod $LASTEXITCODE). Baslatilmadi."; exit $LASTEXITCODE }

$log = Join-Path $Root ".run\server.log"
$outLog = Join-Path $Root ".run\server.out.log"
# Win32_Process.Create: ust kabugun tanitici/borularini miras almayan, tamamen ayrik surec (Start-Process bunlari
# miras alir ve ust kabugu/boruyu sunucu kapanana kadar acik tutar).
$quoted = ($args_ | ForEach-Object { '"' + $_ + '"' }) -join " "
$cmdLine = 'cmd.exe /c ""' + $py + '" ' + $quoted + ' > "' + $outLog + '" 2> "' + $log + '""'
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $cmdLine; CurrentDirectory = $Root }
if ($r.ReturnValue -ne 0) { Write-Error "[start] surec olusturulamadi (kod $($r.ReturnValue))"; exit 1 }
# cmd.exe'nin cocugu olan python PID'ini bul (pid dosyasina onu yaz)
Start-Sleep -Milliseconds 800
$child = Get-CimInstance Win32_Process -Filter "ParentProcessId=$($r.ProcessId)" | Where-Object { $_.Name -like "python*" } | Select-Object -First 1
$serverPid = if ($child) { $child.ProcessId } else { $r.ProcessId }
$serverPid | Out-File $pidFile -Encoding ascii
$p = Get-Process -Id $serverPid -ErrorAction SilentlyContinue
Write-Host "[start] PID $serverPid - log: $log"
# hazir olana kadar bekle (model ilk seferde indirilir, dakikalar surebilir)
$cfg = Get-Content (Join-Path $Root "config.yaml") -Raw
$port = if ($cfg -match "(?m)^\s*port:\s*(\d+)") { $Matches[1] } else { "8000" }
$host_ = if ($cfg -match "(?m)^\s*host:\s*([\d\.]+)") { $Matches[1] } else { "127.0.0.1" }
$ssl = [bool]($cfg -match "(?ms)^\s*ssl:\s*\r?\n\s*enabled:\s*true")
$scheme = if ($ssl) { "https" } else { "http" }
$probe = if ($host_ -eq "0.0.0.0") { "127.0.0.1" } else { $host_ }
$healthUrl = "$scheme`://$probe`:$port/health"
# Prob: curl.exe (Windows 10+ ile gelir; -k kendinden imzali sertifikayi kabul eder). PowerShell 5.1'in
# Invoke-WebRequest'i bu sertifikayla TLS el sikismasini basaramiyor ("unexpected error occurred on a send").
$curl = (Get-Command curl.exe -ErrorAction SilentlyContinue).Source
function Test-Health {
  if ($curl) { $code = & $curl -sk --max-time 2 -o NUL -w "%{http_code}" $healthUrl 2>$null; return ($code -eq "200") }
  try { $r = Invoke-WebRequest -UseBasicParsing $healthUrl -TimeoutSec 2; return ($r.StatusCode -eq 200) } catch { return $false }
}
for ($i = 0; $i -lt 600; $i++) {
  if (-not (Get-Process -Id $serverPid -ErrorAction SilentlyContinue)) { Write-Host "[start] sunucu cikti. Log:"; Get-Content $log -Tail 30; exit 1 }
  if (Test-Health) { break }
  Start-Sleep -Seconds 1
}
Write-Host "[start] hazir: $scheme`://$probe`:$port/   (durdurmak icin .\stop.ps1)"
if ($host_ -eq "0.0.0.0") {
  Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
    ForEach-Object { Write-Host "[start] yerel agdan: $scheme`://$($_.IPAddress):$port/   ($($_.InterfaceAlias))" }
  Write-Host "[start] guvenlik duvari kurali gerekir (bir kez, yonetici): .\service\firewall-allow.ps1"
}
