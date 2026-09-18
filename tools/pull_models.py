#!/usr/bin/env python
"""Secili profilin model agirliklarini KURULUM asamasinda indirir (models/ altina).

Boylece config.yaml'da `offline: true` kalir; sunucu calisirken hicbir dis baglanti denenmez.
Kullanim: python tools/pull_models.py [--profile AD] [--all]
  --all : config'teki butun profillerin modellerini indir (buyuk: large-v3 ~3 GB, turbo ~1.6 GB)
Indirme kaynaklari: Hugging Face Hub (faster-whisper / CTranslate2 agirliklari), openaipublic.azureedge.net
(PyTorch Whisper .pt, sadece backend=whisper profilleri icin). Ses verisi ile ilgisi yoktur.
"""
import argparse
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.config import load_config, resolve_profile  # noqa: E402


def pull(prof, model_dir):
    name = str(prof["model"])
    backend = prof.get("backend", "faster-whisper")
    policy = prof.get("policy", "localagreement")
    needs_ct2 = backend == "faster-whisper" or (policy == "simulstreaming" and not prof.get("disable_fast_encoder"))
    needs_pt = backend == "whisper" or policy == "simulstreaming"
    if needs_ct2:
        from faster_whisper import download_model
        print(f"[pull] faster-whisper/CTranslate2 agirliklari: {name}")
        p = download_model(name, cache_dir=str(model_dir / "whisper"))
        print(f"[pull]   -> {p}")
    if needs_pt:
        from whisperlivekit.whisper import _MODELS, _download
        url = _MODELS.get(name)
        if not url:
            print(f"[pull] UYARI: PyTorch Whisper icin '{name}' bilinmiyor ({', '.join(_MODELS)})")
        else:
            print(f"[pull] PyTorch Whisper .pt: {name}")
            _download(url, str(model_dir / "whisper"), in_memory=False)
    if prof.get("diarization") and prof.get("diarization_backend", "diart") == "diart":
        try:
            import diart.models as m
        except ImportError:
            print("[pull] diarization acik ama diart kurulu degil (setup -Diarization). Atlandi.")
            return
        if not os.environ.get("HF_TOKEN"):
            print("[pull] UYARI: pyannote modelleri kapili; HF_TOKEN ortam degiskeni yok. Diarization modelleri indirilemedi.")
            return
        print("[pull] pyannote segmentation/embedding (HF token ile)")
        m.SegmentationModel.from_pretrained("pyannote/segmentation-3.0")
        m.EmbeddingModel.from_pretrained("pyannote/embedding")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile")
    ap.add_argument("--config")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    cfg = load_config(a.config)
    model_dir = (ROOT / cfg["server"].get("model_dir", "models")).resolve()
    (model_dir / "whisper").mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(model_dir / "hf")
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ.pop("HF_HUB_OFFLINE", None)   # indirme icin gecici olarak online
    names = list(cfg["profiles"]) if a.all else [a.profile or cfg.get("profile")]
    for n in names:
        prof = resolve_profile(cfg, n)
        print(f"== profil {n}: model={prof['model']} backend={prof.get('backend')} policy={prof.get('policy')}")
        pull(prof, model_dir)
    print("[pull] tamam. config.yaml'da offline: true kalabilir.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
