#!/usr/bin/env python
"""audiorec sunucusu: config.yaml + profil -> WhisperLiveKit.

Neden dogrudan `wlk serve` degil:
  * hassasiyet (compute_type), diarization cihazi ve model dizini icin WLK'de CLI bayragi yok -> burada shim
  * Windows'ta CTranslate2'nin cuDNN/cuBLAS DLL'lerini torch'un dizininden bulmasi gerekiyor
  * hazir arayuzde kopyala / .txt indir yok -> `/` rotasi kendi arayuzumuzle degistiriliyor
  * GPU/VRAM on kontrolu (otomatik dusurme yok; sigmiyorsa uyarir ve cikar, --force ile gecilir)

Kullanim: python server.py [--profile AD] [--force] [--print-args]
"""
import argparse
import logging
import os
import sys

if hasattr(sys.stdout, "reconfigure"):  # Windows konsolu cp1252 olabilir; Turkce cikti icin
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from tools.config import PROFILE_UNTESTED_NOTE, load_config, resolve_profile  # noqa: E402


def _env_privacy(server_cfg):
    """Dis baglanti ve telemetri kapatma. Model indirme haric (offline=false iken)."""
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("DO_NOT_TRACK", "1")
    os.environ.setdefault("DISABLE_TELEMETRY", "1")
    os.environ.setdefault("PYTHONWARNINGS", "ignore")
    model_dir = (ROOT / server_cfg.get("model_dir", "models")).resolve()
    (model_dir / "hf").mkdir(parents=True, exist_ok=True)
    (model_dir / "tiktoken").mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(model_dir / "hf"))
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(model_dir / "tiktoken"))
    if server_cfg.get("offline"):
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    return model_dir


def _windows_dll_fix():
    """CTranslate2 (faster-whisper) Windows'ta cudnn/cublas DLL'lerini PATH'te arar; torch ile geliyorlar."""
    if sys.platform != "win32":
        return
    try:
        import torch
        lib = Path(torch.__file__).parent / "lib"
        if lib.is_dir():
            os.add_dll_directory(str(lib))
            os.environ["PATH"] = str(lib) + os.pathsep + os.environ.get("PATH", "")
    except Exception as e:  # noqa: BLE001
        print(f"[server] uyari: torch DLL dizini eklenemedi: {e}", file=sys.stderr)


def _shim_compute_type(prof):
    """faster_whisper.WhisperModel'e profilin compute_type/device degerini enjekte et.
    WLK kodu compute_type='auto' ve device='auto' ile cagiriyor; bayrak yok."""
    import faster_whisper

    want_ct = str(prof.get("compute_type", "auto"))
    want_dev = str(prof.get("device", "cuda"))
    base = faster_whisper.WhisperModel

    class PatchedWhisperModel(base):  # type: ignore[misc,valid-type]
        def __init__(self, *args, **kwargs):
            kwargs["compute_type"] = want_ct
            kwargs["device"] = want_dev
            logging.getLogger("audiorec").warning(
                "faster-whisper: model=%s device=%s compute_type=%s", args[0] if args else "?", want_dev, want_ct)
            super().__init__(*args, **kwargs)

    faster_whisper.WhisperModel = PatchedWhisperModel


def _shim_diarization_device(prof):
    """diart SpeakerDiarizationConfig'e device enjekte et (WLK device vermiyor; diart varsayilani cuda)."""
    if not prof.get("diarization"):
        return
    if prof.get("diarization_backend", "diart") != "diart":
        return
    try:
        import diart
        import torch
    except ImportError:
        raise SystemExit("diarization acik ama diart kurulu degil. Kurulum: setup.ps1 -Diarization / setup.sh --diarization")
    dev = torch.device(str(prof.get("diarization_device", "cuda")))
    base = diart.SpeakerDiarizationConfig

    class PatchedConfig(base):  # type: ignore[misc,valid-type]
        def __init__(self, *args, **kwargs):
            kwargs["device"] = dev
            logging.getLogger("audiorec").warning("diart: device=%s", dev)
            super().__init__(*args, **kwargs)

    diart.SpeakerDiarizationConfig = PatchedConfig
    import whisperlivekit.diarization.diart_backend as db
    db.SpeakerDiarizationConfig = PatchedConfig


def build_wlk_argv(cfg, prof, model_dir):
    s = cfg["server"]
    argv = [
        "--host", str(s.get("host", "127.0.0.1")),
        "--port", str(s.get("port", 8000)),
        "--lan", str(s.get("language", "tr")),
        "--log-level", str(s.get("log_level", "WARNING")),
        "--model", str(prof["model"]),
        "--backend", str(prof.get("backend", "faster-whisper")),
        "--backend-policy", str(prof.get("policy", "localagreement")),
        "--min-chunk-size", str(s.get("min_chunk_size", 0.5)),
        "--model_cache_dir", str(model_dir / "whisper"),
        f"--warmup-file={s.get('warmup_file', '')}",
    ]
    if s.get("pcm_input", True):
        argv.append("--pcm-input")
    if s.get("retention_seconds") is not None:
        argv += ["--retention-seconds", str(s["retention_seconds"])]
    if prof.get("disable_fast_encoder"):
        argv.append("--disable-fast-encoder")
    if prof.get("diarization"):
        argv += ["--diarization", "--diarization-backend", str(prof.get("diarization_backend", "diart"))]
    if s.get("api_token"):
        argv += ["--api-token", str(s["api_token"])]
    argv += [str(x) for x in (s.get("extra_args") or [])]
    argv += [str(x) for x in (prof.get("extra_args") or [])]
    return argv


def resolve_ssl(server_cfg):
    """(certfile, keyfile) ya da None. LAN'a TLS'siz acmayi reddeder."""
    host = str(server_cfg.get("host", "127.0.0.1"))
    local_only = host in ("127.0.0.1", "localhost", "::1")
    ssl = server_cfg.get("ssl") or {}
    if ssl.get("enabled"):
        crt = (ROOT / str(ssl.get("certfile", "certs/audiorec.crt"))).resolve()
        key = (ROOT / str(ssl.get("keyfile", "certs/audiorec.key"))).resolve()
        if not (crt.is_file() and key.is_file()):
            raise SystemExit(f"ssl.enabled=true ama sertifika yok: {crt} / {key}\n"
                             "  uret: .venv/Scripts/python.exe tools/make_cert.py")
        return str(crt), str(key)
    if not local_only and not server_cfg.get("allow_insecure_lan"):
        raise SystemExit(f"host={host} yerel aga acik ama ssl.enabled=false. Tarayici mikrofonu HTTPS'siz acmaz ve ses "
                         "sifresiz giderdi. config.yaml: ssl.enabled: true (+ tools/make_cert.py) ya da host: 127.0.0.1")
    return None


def lan_ipv4s():
    import socket
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except socket.gaierror:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


def _set_log_levels(level_name):
    level = getattr(logging, level_name.upper(), logging.WARNING)
    logging.getLogger().setLevel(level)
    for name, lg in list(logging.Logger.manager.loggerDict.items()):
        if isinstance(lg, logging.Logger) and (name.startswith("whisperlivekit") or name.startswith("uvicorn")
                                               or name.startswith("diart") or name.startswith("faster_whisper")):
            lg.setLevel(level)
    logging.getLogger("audiorec").setLevel(logging.INFO)


def _custom_ui_html():
    from whisperlivekit import get_inline_ui_html
    html = get_inline_ui_html()
    extra = (ROOT / "web" / "toolbar.html").read_text(encoding="utf-8")
    marker = '<p id="status"></p>'
    if marker in html:
        html = html.replace(marker, marker + "\n" + extra, 1)
    else:
        html = html.replace("</body>", extra + "\n</body>", 1)
    return html.replace("<title>WhisperLiveKit</title>", "<title>audiorec - canli transkript</title>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile")
    ap.add_argument("--config")
    ap.add_argument("--force", action="store_true", help="VRAM kontrolu basarisiz olsa da baslat")
    ap.add_argument("--print-args", action="store_true", help="WLK argumanlarini yazdir ve cik")
    a = ap.parse_args()

    cfg = load_config(a.config)
    prof = resolve_profile(cfg, a.profile)
    model_dir = _env_privacy(cfg["server"])
    argv = build_wlk_argv(cfg, prof, model_dir)
    if a.print_args:
        print("wlk serve " + " ".join(argv))
        ssl = cfg["server"].get("ssl") or {}
        print(f"host={cfg['server'].get('host')} ssl={'on' if ssl.get('enabled') else 'off'} "
              f"({ssl.get('certfile')}, {ssl.get('keyfile')})")
        return 0

    log = logging.getLogger("audiorec")
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log.setLevel(logging.INFO)
    log.info("profil: %s - %s", prof["name"], prof.get("description", ""))
    if not prof.get("tested"):
        log.warning("profil '%s': %s", prof["name"], PROFILE_UNTESTED_NOTE)

    # 1) GPU / VRAM on kontrolu (otomatik dusurme yok)
    import subprocess
    rc = subprocess.call([sys.executable, str(ROOT / "tools" / "check_gpu.py"), "--profile", prof["name"],
                         "--config", a.config or str(ROOT / "config.yaml")] + (["--force"] if a.force else []))
    if rc == 2:
        log.error("profil bu karta sigmiyor; baslatilmadi. Baska profil sec ya da --force ile dene.")
        return 2
    if rc not in (0,):
        log.error("GPU kontrolu hata verdi (kod %s)", rc)
        return rc

    # 2) shim'ler ve WLK import (parse_args import aninda calisir -> argv'yi once kur)
    _windows_dll_fix()
    _shim_compute_type(prof)
    _shim_diarization_device(prof)
    sys.argv = ["wlk"] + argv
    import whisperlivekit.basic_server as bs
    _set_log_levels(cfg["server"].get("log_level", "WARNING"))

    # 3) arayuz: '/' rotasini kopyala/indir butonlu surumle degistir
    from fastapi.responses import HTMLResponse
    bs.app.router.routes = [r for r in bs.app.router.routes if getattr(r, "path", None) != "/"]

    @bs.app.get("/")
    async def index():  # noqa: WPS430
        return HTMLResponse(_custom_ui_html())

    @bs.app.get("/profile")
    async def profile_info():  # noqa: WPS430
        return {"profile": prof["name"], "model": prof["model"], "backend": prof.get("backend"),
                "policy": prof.get("policy"), "compute_type": prof.get("compute_type"),
                "diarization": bool(prof.get("diarization")), "language": cfg["server"].get("language")}

    # 4) calistir
    import uvicorn
    s = cfg["server"]
    ssl = resolve_ssl(s)
    scheme = "https" if ssl else "http"
    host, port = str(s.get("host", "127.0.0.1")), int(s.get("port", 8000))
    urls = [f"{scheme}://127.0.0.1:{port}/"]
    if host not in ("127.0.0.1", "localhost", "::1"):
        urls += [f"{scheme}://{ip}:{port}/" for ip in (lan_ipv4s() if host in ("0.0.0.0", "::") else [host])]
    log.info("dinleniyor: %s  (wlk argv: %s)", "  ".join(urls), " ".join(argv))
    kw = {}
    if ssl:
        kw = {"ssl_certfile": ssl[0], "ssl_keyfile": ssl[1]}
    uvicorn.run(bs.app, host=host, port=port, log_level=str(s.get("log_level", "WARNING")).lower(),
                lifespan="on", access_log=False, **kw)
    return 0


if __name__ == "__main__":
    sys.exit(main())
