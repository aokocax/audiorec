"""config.yaml okuma ve profil cozumleme (server.py, check_gpu.py, bench.py ortak kullanir)."""
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PROFILE_UNTESTED_NOTE = ("bu profil bu donanimda TEST EDILMEDI; degerler tahmindir. "
                         "Yeni donanimda once bench.ps1 / bench.sh calistir.")


def load_config(path=None):
    path = Path(path or os.environ.get("AUDIOREC_CONFIG") or ROOT / "config.yaml")
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg.setdefault("profiles", {})
    cfg.setdefault("server", {})
    return cfg


def resolve_profile(cfg, name=None):
    name = name or os.environ.get("AUDIOREC_PROFILE") or cfg.get("profile")
    if name not in cfg["profiles"]:
        raise SystemExit(f"profil '{name}' config.yaml icinde yok. Mevcut: {', '.join(cfg['profiles'])}")
    prof = dict(cfg.get("profile_defaults", {}))
    prof.update(cfg["profiles"][name] or {})
    prof["name"] = name
    return prof
