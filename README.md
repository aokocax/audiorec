# audiorec — yerel, canlı Türkçe transkript (WhisperLiveKit)

İki kişinin yüz yüze konuşmasını tarayıcı mikrofonundan alıp **tamamen bu makinede** yazıya döker.

**Gizlilik kuralları (pazarlıksız):**
1. Hiçbir ses verisi bu ağın dışına çıkmaz (LAN modunda istemci→sunucu TLS ile şifreli). Bulut API yok, telemetri kapalı (`HF_HUB_DISABLE_TELEMETRY=1`, `DO_NOT_TRACK=1`). Tek dış bağlantı: ilk çalıştırmada model ağırlıklarının indirilmesi; sonrasında `offline: true` ile bu da kapatılır.
2. Ses hiçbir aşamada diske yazılmaz. Tarayıcı ham PCM'i websocket ile gönderir (`--pcm-input`, ffmpeg yok), sunucu bellekte işler ve atar. WLK'nin varsayılan "warmup" özelliği internetten örnek ses indirip temp'e yazdığı için **kapatıldı** (`warmup_file: ""`). Log seviyesi `WARNING` (DEBUG/INFO transkript metnini loga düşürebilir).
3. Transkript sunucuda saklanmaz; sadece tarayıcı belleğindedir. "Kopyala" ve ".txt indir" tarayıcı tarafında çalışır.

Bu kurulum **Windows 11 + RTX 2060 6 GB** üzerinde geliştirildi ve test edildi. Linux script'leri (`*.sh`, systemd) yazıldı ama **test edilmedi**.

---

## 1. Kurulum

Gereksinimler: NVIDIA sürücüsü (CUDA 12.6+ destekleyen, yani ≥ 560), internet (sadece kurulum ve ilk model indirme). Python/ffmpeg/CUDA toolkit kurmana gerek yok: `uv` Python 3.12'yi proje içine (`.python/`) indirir, torch kendi CUDA kütüphanelerini getirir.

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1            # temel
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Diarization   # + konuşmacı ayrımı (bkz. §6)
```

Linux (test edilmedi):
```bash
./setup.sh              # ./setup.sh --diarization
```

Kurulum sonunda `tools/check_gpu.py --setup-check` torch'un GPU'yu gördüğünü doğrular.

### Sürücü/CUDA'ya sıkı bağlı paketler
| Paket | Sürüm | Bağımlılık |
|---|---|---|
| `torch`, `torchaudio` | 2.8.0+cu126 | NVIDIA sürücü ≥ 560 (CUDA 12.6). Sürücü 566.03 ile test edildi. cu128 wheel'leri sürücü ≥ 570 ister; cu126 bu yüzden seçildi. |
| `ctranslate2` | 4.8.2 | CUDA 12 + cuDNN 9. Windows'ta DLL'leri torch'un `torch\lib` dizininden alır (`server.py` bunu PATH'e ekler). |
| `onnxruntime` | 1.30 | CPU (Silero VAD için); GPU gerekmez. |
| `torchvision` (sadece diarization) | 0.23.0+cu126 | torch ile aynı CUDA sürümü olmalı. |

Yeni makinede sürücü daha eskiyse `setup.ps1`/`setup.sh` içindeki `TorchIdx`/`TORCH_IDX` değerini (`cu121`, `cu124` …) değiştirip `-NoLock`/`--no-lock` ile yeniden çöz.

## 2. Başlatma / durdurma

```powershell
.\start.ps1 -Profile dev-6gb        # arka planda; PID .run\server.pid, log .run\server.log
.\start.ps1 -Profile dev-6gb -Foreground
.\stop.ps1
```
Linux: `./start.sh dev-6gb`, `./stop.sh`.

Başlangıçta `tools/check_gpu.py` GPU'yu ve boş VRAM'i okur; seçili profil sığmıyorsa **başlatmaz**, nedenini ve sığan en büyük profili önerir. Otomatik düşürme yapılmaz; `-Force` ile yine de denenebilir.

Modeller kurulumda indirilir (`setup` sonunda `tools/pull_models.py`, `models/` altına; turbo ≈ 1.6 GB, large-v3 ≈ 3 GB). `config.yaml`'da `offline: true` varsayılandır: sunucu çalışırken hiçbir dış bağlantı denenmez. Modeli henüz inmemiş bir profile geçerken önce indir:
```powershell
.\.venv\Scripts\python.exe tools\pull_models.py --profile dev-6gb-large     # ya da --all
```

### Servis olarak (varsayılan: kapalı)
- Windows: `.\service\install-task.ps1 -Profile dev-6gb` → Görev Zamanlayıcı'da **devre dışı** bir görev oluşturur. Etkinleştirmek: `Enable-ScheduledTask -TaskName audiorec`.
- Linux (test edilmedi): `service/audiorec.service` → `/etc/systemd/system/`, yolları düzenle, `systemctl start audiorec`. `enable` etmedikçe açılışta başlamaz.

## 3. Bağlanma

`config.yaml` → `server.host`:
- `127.0.0.1`: sadece bu makine. Tarayıcıda `http://127.0.0.1:8000/` (localhost'ta HTTPS gerekmez).
- `0.0.0.0` (**şu anki ayar**): yerel ağdaki cihazlar da bağlanır. Bu durumda `ssl.enabled: true` zorunludur; `server.py` TLS'siz LAN'a açılmayı reddeder. Neden: tarayıcılar mikrofonu yalnızca localhost ya da HTTPS sayfada açar, ayrıca ses LAN'da şifresiz gitmesin.

### Yerel ağa açma adımları (bir kez)
1. Sertifika: `.\.venv\Scripts\python.exe tools\make_cert.py` → `certs/audiorec.crt` + `.key` (kendinden imzalı, 825 gün; SAN: makine adı, 127.0.0.1 ve tüm yerel IP'ler; IP değişirse `--force` ile yenile).
2. Güvenlik duvarı (**yönetici PowerShell**, ben eklemedim): `.\service\firewall-allow.ps1` → TCP 8000, yalnızca `LocalSubnet`. Kaldırmak: `-Remove`. Wi-Fi profilin "Public" ise gerekirse `Set-NetConnectionProfile -InterfaceAlias "Wi-Fi" -NetworkCategory Private`.
3. `.\start.ps1 -Profile dev-6gb` → yerel ağ adreslerini yazar (ör. `https://192.168.3.173:8000/`).
4. İstemci tarayıcıda adresi aç; "güvenli değil" uyarısında devam et (ya da `certs/audiorec.crt` dosyasını istemciye "Güvenilen Kök Sertifika" olarak yükle, uyarı kalkar). Arayüz sayfa HTTPS olduğu için websocket'i otomatik `wss://` yapar.
5. İsteğe bağlı: `api_token: "..."` ile websocket `?token=` ister (LAN'daki başkalarının GPU'yu kullanmasını engeller; arayüzde ws adresine `?token=...` eklenir).

İnternete açma. LAN dışından erişim için SSH tüneli:
```powershell
ssh -N -L 8000:127.0.0.1:8000 KULLANICI@SUNUCU_ADRESI
```

Arayüz: Kayıt düğmesi → konuş → satırlar canlı gelir. Üstteki **Kopyala** / **.txt indir** düğmeleri transkripti panoya/dosyaya verir ("zaman damgası" seçeneğiyle). Sayfayı yenilersen transkript gider (bilerek: sunucu saklamaz).

Doğrulandı (2026-09-18): `https://192.168.3.173:8000/health` OK, düz HTTP bağlantı kabul edilmiyor, LAN IP üzerinden `wss://` ile bench WER %2.9, gecikme medyan 1.3 s.

## 4. Profil değiştirme

`config.yaml` → `profiles:` altında. Seçim: `start.ps1 -Profile AD`, `./start.sh AD` ya da `AUDIOREC_PROFILE=AD`. Varsayılan `profile:` anahtarı.

Profil alanları: `model`, `backend` (faster-whisper | whisper), `policy` (localagreement | simulstreaming), `compute_type` (float16 | int8_float16 | int8 | auto), `disable_fast_encoder`, `diarization`, `diarization_backend`, `diarization_device` (cuda | cpu), `vram_required_mb`, `tested`, `extra_args`.

`compute_type` ve `diarization_device` için WLK'de CLI bayrağı yok; `server.py` bunları küçük bir shim ile (`faster_whisper.WhisperModel` ve `diart.SpeakerDiarizationConfig` sarmalanarak) enjekte eder. `python server.py --print-args` üretilen `wlk serve` komutunu gösterir.

## 5. Ölçüm (bench)

Donanım değişince ilk iş:
```powershell
.\stop.ps1                       # bench kendi sunucusunu açar
.\bench.ps1 -Profile dev-6gb     # test sesi yoksa Windows'un Türkçe sesiyle (Tolga) üretir, sonunda siler
.\bench.ps1 -Profile mid-12gb -Audio ornek.wav -RefText "..."
```
Linux: `./bench.sh PROFIL ses.wav ["referans metin"] [sessizlik_sn]` (Linux'ta yerleşik Türkçe TTS yok; kamuya açık/sentetik bir Türkçe örnek ver, sonunda sil).

Raporlanan: model yüklü/tepe VRAM (sistem toplamının başlangıca göre artışı; Windows WDDM süreç bazlı vermez), başlangıç süresi, ilk metin, onaylı metin gecikmesi (medyan/p90), sunucunun bildirdiği işleme gecikmesi, son ses→kesinleşme, sessizlik testi (VAD), WER. Sonuç `bench-results/*.json` (ses içermez). Ölçtüğün tepe VRAM + ~500 MB payı profilin `vram_required_mb` alanına yaz.

## 6. Konuşmacı ayrımı (diarization)

`diart` backend'i pyannote modellerini kullanır (`pyannote/segmentation-3.0`, `pyannote/embedding`). Bunlar Hugging Face'te **kapılı**: bir HF hesabıyla model sayfalarındaki şartları kabul edip bir okuma token'ı almak ve sunucuyu `HF_TOKEN=...` ortam değişkeniyle başlatmak gerekir. Token sadece model indirmede kullanılır; ses HF'ye gitmez. İndirme bittikten sonra `offline: true` ile bağlantı kapatılır.

`sortformer` backend'i NeMo ister; Windows'ta kurulmadı ve denenmedi.

## 7. Yeni donanıma taşıma

1. Proje dizinini kopyala (`.venv/`, `.python/`, `models/` hariç; hepsi yeniden üretilir; `models/` kopyalanırsa indirme atlanır).
2. NVIDIA sürücüsünü kontrol et: `nvidia-smi` → CUDA sürümü ≥ 12.6 ise dokunma; değilse §1'deki torch index'ini değiştir.
3. `setup.ps1` / `setup.sh` çalıştır.
4. `python tools/check_gpu.py --profile <aday>` ile uygunluğu gör; `bench` ile ölç; `vram_required_mb` ve `tested: true` alanlarını güncelle.
5. Linux'ta: `service/audiorec.service` yollarını düzenle. Tünel komutu §3.

## 8. Ölçüm sonuçları (RTX 2060 6 GB, Windows 11, 2026-09-18)

Test: Windows Tolga sesiyle üretilen 16–20 s Türkçe konuşma + 20 s sessizlik, gerçek zamanlı websocket akışı (`bench.py`). VRAM = sistem toplamının sunucu öncesine göre artışı (ekran bağlı; masaüstü ~1.5–2.7 GB tutuyordu).

| Profil | Model / backend | Model VRAM | Tepe VRAM | İlk metin | Onaylı metin gecikmesi (medyan / p90) | WER | Sessizlik |
|---|---|---|---|---|---|---|---|
| **dev-6gb** (varsayılan) | large-v3-turbo, faster-whisper int8_float16, LocalAgreement | ~0.85–1.2 GB | ~1.1–1.5 GB | 1.1 s | 1.0–1.5 s / 1.6–1.8 s | 2.9–3.6 % | 20 s'de metin yok |
| dev-6gb-large | large-v3, faster-whisper int8_float16, LocalAgreement | ~1.5 GB | ~1.9 GB | 1.1 s | 1.8 s / 4.1 s | 7.1 % (son kelime kesinleşmedi) | 20 s'de metin yok |
| dev-6gb-simul | large-v3-turbo, SimulStreaming (PyTorch decoder + CT2 encoder) | ~3.8 GB | **~3.9 GB (toplam 5.7/6 GB)** | 6.8 s | 24 s / 37 s | 3.6 % | metin 20 s gecikmeli aktı |

Kararlar:
- **dev-6gb = turbo + faster-whisper int8_float16.** Daha doğru ve daha düşük gecikmeli çıktı verdi; large-v3 int8 bu testte daha kötü çıktı (küçük örnek, tek konuşmacı; kendi konuşmalarında `dev-6gb-large` ile karşılaştır).
- **SimulStreaming 6 GB'da güvenli değil**: PyTorch modeli + CTranslate2 encoder'ı çift yükleniyor, kart dolunca gecikme saniyelerden onlarca saniyeye çıkıyor. Profil "ölçüldü, önerilmez" olarak duruyor; `check_gpu` normal koşulda reddeder. 24 GB profilinde kullanılması planlandı (test edilmedi).
- **Diarization test edilemedi**: diart'ın pyannote modelleri HF'de kapılı; token olmadan indirilemiyor. dev-6gb'de kapalı. Token verirsen `setup.ps1 -Diarization` + `diarization: true` (GPU/CPU seçimi `diarization_device`) ile ölçülür.
- VAD/VAC açık: 20 s sessizlikte hiçbir profil yeni metin üretmedi (SimulStreaming'de görülen değişiklikler gecikmiş gerçek metindi, uydurma değil).
- Gizlilik denetimi: çalışma boyunca proje dizini, temp, `~/.cache`, `%LOCALAPPDATA%` altında ses uzantılı dosya oluşmadı (`tools/privacy_audit.py`). `offline: true` ile 10+ dk çalışan sunucunun tek soketi `127.0.0.1:8000 LISTEN` idi. İlk kurulumdaki tek dış bağlantı HF Hub/CloudFront model indirmesiydi.
- Tarayıcı arayüzü: `http://127.0.0.1:8000/` açılıyor, "Kopyala / .txt indir" düğmeleri ve zaman damgası seçeneği çalışıyor (mikrofon testi kendi tarayıcında; sunucu tarafında mikrofon yok).

## 9. Bilinen sınırlar

- **Windows WDDM**: nvidia-smi süreç bazlı VRAM göstermez; bench sistem toplamındaki artışı ölçer (başka uygulama aynı anda VRAM alırsa sayıya karışır).
- **Warmup kapalı**: ilk cümlede tek seferlik ek gecikme olur (CUDA kernel/graph ısınması).
- **Sessizlikte uydurma**: Whisper'ın bilinen davranışı; VAD/VAC açık (varsayılan) ve bench'in sessizlik testiyle doğrulanır. Çok gürültülü ortamda yine de kısa uydurmalar olabilir.
- **large-v3 fp16** 6 GB karta sığmaz (ağırlıklar ~3 GB + aktivasyon + diğer uygulamalar). 6 GB'da large-v3 için `int8_float16` (profil `dev-6gb-large`).
- **Ekran bağlı GPU**: Windows masaüstü/tarayıcılar 1.5–2 GB VRAM tutar; bench'i ve gerçek kullanımı bu koşulda değerlendir.
- `mid-12gb` ve `high-24gb` profilleri **test edilmemiştir**; `vram_required_mb` tahmindir.
- Transkript dosya adı ve içeriği tarayıcının indirme klasörüne gider; bu bilinçli bir kullanıcı eylemidir.
- `bench-results/*.json` içinde test transkripti metni vardır (ses yok). Gerçek konuşmayla bench yapma; sentetik/kamuya açık ses kullan.
- PowerShell script'leri UTF-8 **BOM'lu** kaydedilmelidir (Türkçe metin için); BOM'suz kaydedersen Tolga bozuk metin okur, WER anlamsız çıkar.
- `start.ps1` hazır-olma probunu `curl.exe` ile yapar; PowerShell 5.1'in `Invoke-WebRequest`'i kendinden imzalı ECDSA sertifikayla el sıkışamıyor.
- `start.ps1` sunucuyu `Win32_Process.Create` ile ayrık başlatır; `Start-Process` kullanılırsa üst kabuğun boruları miras alınıp betik takılı görünür.
