<#
  audiorec - Windows guvenlik duvari kurali (YONETICI olarak calistir). Sadece yerel alt agdan (LocalSubnet)
  TCP 8000'e gelen baglantiya izin verir; internetten erisim acilmaz.
  Kullanim:  .\service\firewall-allow.ps1 [-Port 8000] [-Remove]
  Not: Ag profili "Public" ise Windows bazi kurallari yine kisitlayabilir; agini "Private" yapmak icin:
       Set-NetConnectionProfile -InterfaceAlias "Wi-Fi" -NetworkCategory Private
#>
param([int]$Port = 8000, [switch]$Remove)
$ErrorActionPreference = "Stop"
$name = "audiorec LAN (TCP $Port)"
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Write-Error "Yonetici PowerShell'de calistir."; exit 1
}
if ($Remove) { Remove-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue; Write-Host "[fw] kaldirildi: $name"; exit 0 }
Remove-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName $name -Direction Inbound -Protocol TCP -LocalPort $Port -RemoteAddress LocalSubnet `
  -Profile Any -Action Allow -Description "audiorec yerel transkript sunucusu; sadece yerel alt ag" | Out-Null
Write-Host "[fw] eklendi: $name  (RemoteAddress=LocalSubnet)"
Get-NetFirewallRule -DisplayName $name | Select-Object DisplayName,Enabled,Profile,Direction,Action | Format-Table -AutoSize
