<#
  Windows'un yerlesik Turkce sesi (Microsoft Tolga, OneCore) ile sentetik test sesi uretir. Internet kullanmaz.
  Kullanim: .\tools\make_test_audio.ps1 -Out C:\...\test.wav [-Text "..."]
  Cikti: referans metni (stdout) - WER icin.  Dosya isi bitince silinmeli (bench.ps1 bunu otomatik yapar).
#>
param(
  [Parameter(Mandatory=$true)][string]$Out,
  [string]$Text = "Merhaba, bugün toplantıda üç konuyu ele alacağız. Birincisi, geçen haftaki satış rakamları. İkincisi, yeni ürünün piyasaya sürülme tarihi. Üçüncüsü ise müşteri geri bildirimleri. Sizce hangi konuyla başlayalım? Bence önce rakamlara bakalım, sonra takvimi konuşuruz."
)
$ErrorActionPreference = "Stop"
$null = [Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media, ContentType=WindowsRuntime]
$null = [Windows.Storage.Streams.DataReader, Windows.Storage.Streams, ContentType=WindowsRuntime]
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($WinRtTask, $ResultType) { $asTask = $asTaskGeneric.MakeGenericMethod($ResultType); $t = $asTask.Invoke($null, @($WinRtTask)); $t.Wait(-1) | Out-Null; $t.Result }
$synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
$voice = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices | Where-Object { $_.Language -like "tr*" } | Select-Object -First 1
if (-not $voice) { Write-Error "Turkce TTS sesi yok. Ayarlar > Zaman ve dil > Konusma > Ses ekle > Turkce (Tolga)"; exit 1 }
$synth.Voice = $voice
$stream = Await ($synth.SynthesizeTextToStreamAsync($Text)) ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
$size = $stream.Size
$reader = New-Object Windows.Storage.Streams.DataReader($stream.GetInputStreamAt(0))
$null = Await ($reader.LoadAsync([uint32]$size)) ([uint32])
$bytes = New-Object byte[] $size
$reader.ReadBytes($bytes)
[System.IO.File]::WriteAllBytes($Out, $bytes)
Write-Output $Text
