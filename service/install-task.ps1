<#
  audiorec - Windows Gorev Zamanlayici kaydi (systemd karsiligi). Gorev DEVRE DISI olarak olusturulur.
  Kullanim:  .\service\install-task.ps1 [-Profile dev-6gb] [-Remove]
  Etkinlestirmek (bilincli karar):  Enable-ScheduledTask -TaskName audiorec
  Elle baslat/durdur:               Start-ScheduledTask / Stop-ScheduledTask -TaskName audiorec
  Gorev, kullanici oturum actiginda server.py'yi secili profille baslatir (sadece 127.0.0.1'e baglanir).
#>
param([string]$Profile = "dev-6gb", [switch]$Remove)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$name = "audiorec"
if ($Remove) { Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue; Write-Host "[task] kaldirildi"; exit 0 }
$py = Join-Path $Root ".venv\Scripts\python.exe"
$action = New-ScheduledTaskAction -Execute $py -Argument "server.py --profile $Profile" -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -Hidden
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Description "audiorec yerel transkript sunucusu (varsayilan: devre disi)" -Force | Out-Null
Disable-ScheduledTask -TaskName $name | Out-Null
Write-Host "[task] '$name' olusturuldu ve DEVRE DISI birakildi. Etkinlestirmek icin: Enable-ScheduledTask -TaskName $name"
