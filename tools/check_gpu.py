#!/usr/bin/env python
"""GPU / VRAM kontrolu ve profil uygunlugu.

Kullanim:
  python tools/check_gpu.py --profile dev-6gb        # secili profil karta sigiyor mu? (cikis kodu 2: sigmiyor)
  python tools/check_gpu.py --setup-check            # kurulum sonrasi: torch CUDA goruyor mu?
  python tools/check_gpu.py --json                   # makine tarafindan okunabilir cikti

Otomatik profil dusurme YAPMAZ; sadece uyarir ve uygun profili onerir.
"""
import argparse
import json
import shutil
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):  # Windows konsolu cp1252 olabilir; Turkce cikti icin
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.config import PROFILE_UNTESTED_NOTE, load_config  # noqa: E402


def query_nvidia_smi():
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.check_output(
            [exe, "--query-gpu=name,memory.total,memory.used,memory.free,driver_version,compute_cap",
             "--format=csv,noheader,nounits"], text=True, timeout=15)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    gpus = []
    for line in out.strip().splitlines():
        name, total, used, free, drv, cc = [x.strip() for x in line.split(",")]
        gpus.append({"name": name, "total_mb": int(float(total)), "used_mb": int(float(used)),
                     "free_mb": int(float(free)), "driver": drv, "compute_cap": cc})
    return gpus


def query_processes():
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        out = subprocess.check_output([exe, "--query-compute-apps=pid,process_name,used_memory",
                                       "--format=csv,noheader,nounits"], text=True, timeout=15)
        rows = []
        for line in out.splitlines():
            parts = [x.strip() for x in line.split(",")]
            if len(parts) == 3 and parts[2].replace(".", "").isdigit():   # WDDM'de [N/A] gelir; onlari atla
                rows.append(f"{parts[0]}  {parts[1]}  {parts[2]} MB")
        return rows
    except Exception:  # noqa: BLE001
        return []


def torch_info():
    try:
        import torch
    except Exception as e:  # noqa: BLE001
        return {"available": False, "error": f"torch import basarisiz: {e}"}
    info = {"available": torch.cuda.is_available(), "torch": torch.__version__, "cuda": torch.version.cuda}
    if info["available"]:
        p = torch.cuda.get_device_properties(0)
        info.update({"name": p.name, "capability": f"{p.major}.{p.minor}", "total_mb": p.total_memory // 2**20,
                     "bf16": torch.cuda.is_bf16_supported(including_emulation=False)})
        free, _total = torch.cuda.mem_get_info(0)
        info["free_mb"] = free // 2**20
    return info


def fits(profile, gpu, tinfo):
    """(ok, reasons) - profil bu karta uygun mu?"""
    reasons = []
    need = int(profile.get("vram_required_mb", 0))
    if gpu is None:
        if profile.get("device", "cuda") == "cuda":
            reasons.append("GPU bulunamadi (nvidia-smi yok) ama profil CUDA istiyor")
        return (not reasons), reasons
    if need and gpu["free_mb"] < need:
        reasons.append(f"bos VRAM {gpu['free_mb']} MB < profilin ihtiyaci {need} MB")
    ct = str(profile.get("compute_type", ""))
    if "bfloat16" in ct and tinfo.get("available") and not tinfo.get("bf16"):
        reasons.append("profil bfloat16 istiyor, bu kart desteklemiyor (Turing/Volta)")
    if ct in ("float16", "int8_float16") and float(gpu["compute_cap"]) < 7.0:
        reasons.append("fp16 icin compute capability >= 7.0 gerekir")
    return (not reasons), reasons


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--setup-check", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--force", action="store_true", help="sigmasa da cikis kodu 0 (start.* --force icin)")
    a = ap.parse_args()

    gpus = query_nvidia_smi()
    gpu = gpus[0] if isinstance(gpus, list) and gpus else None
    tinfo = torch_info()

    if a.json:
        print(json.dumps({"gpu": gpu, "torch": tinfo, "processes": query_processes()}, indent=2))
        return 0

    print("== GPU ==")
    if gpu:
        print(f"  {gpu['name']}  toplam {gpu['total_mb']} MB, kullanimda {gpu['used_mb']} MB, bos {gpu['free_mb']} MB")
        print(f"  surucu {gpu['driver']}, compute capability {gpu['compute_cap']}")
        procs = query_processes()
        if procs:
            print("  GPU kullanan diger surecler (nvidia-smi):")
            for p in procs:
                print("    ", p)
        else:
            print("  (surec bazli VRAM gorunmuyor - Windows WDDM ya da bos; 'kullanimda' degerine bak)")
    else:
        print("  nvidia-smi bulunamadi ya da GPU yok")
    print("== torch ==")
    if tinfo.get("available"):
        print(f"  torch {tinfo['torch']} CUDA {tinfo['cuda']}  cihaz {tinfo['name']}  "
              f"bf16={'evet' if tinfo['bf16'] else 'hayir'}")
    else:
        print(f"  CUDA kullanilamiyor: {tinfo.get('error', 'torch.cuda.is_available()=False')}")

    if a.setup_check:
        return 0 if tinfo.get("available") else 1

    cfg = load_config(a.config)
    prof_name = a.profile or cfg.get("profile")
    profiles = cfg["profiles"]
    if prof_name not in profiles:
        print(f"HATA: profil '{prof_name}' config.yaml icinde yok. Mevcut: {', '.join(profiles)}")
        return 1
    prof = dict(cfg.get("profile_defaults", {}))
    prof.update(profiles[prof_name] or {})
    ok, reasons = fits(prof, gpu, tinfo)
    print(f"== profil: {prof_name} ==  ({prof.get('description', '')})")
    if not prof.get("tested", False):
        print("  UYARI: " + PROFILE_UNTESTED_NOTE)
    if ok:
        print("  uygun: evet")
        return 0
    print("  UYGUN DEGIL:")
    for r in reasons:
        print("   -", r)
    cands = []
    for n, p in profiles.items():
        full = dict(cfg.get("profile_defaults", {}))
        full.update(p or {})
        if fits(full, gpu, tinfo)[0]:
            cands.append((n, full))
    if cands:
        best = max(cands, key=lambda np_: int(np_[1].get("vram_required_mb", 0)))
        print(f"  Oneri: --profile {best[0]}  ({best[1].get('description', '')})")
    else:
        print("  Oneri: hicbir profil sigmiyor; GPU kullanan diger uygulamalari kapat ya da daha kucuk model sec")
    print("  Otomatik dusurme yapilmadi. Yine de denemek icin: --force")
    return 0 if a.force else 2


if __name__ == "__main__":
    sys.exit(main())
