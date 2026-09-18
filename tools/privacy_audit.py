#!/usr/bin/env python
"""Gizlilik denetimi: calisma sirasinda yeni dosya olusuyor mu, surec disariya baglaniyor mu?

Kullanim:
  python tools/privacy_audit.py snapshot --out before.json          # calismadan ONCE
  ... sunucuyu calistir, ses gonder ...
  python tools/privacy_audit.py diff --before before.json             # yeni/degisen dosyalari listele
  python tools/privacy_audit.py connections --pid <PID>               # surecin (ve alt sureclerinin) TCP baglantilari

Izlenen dizinler: proje dizini, sistem temp, ~/.cache, %LOCALAPPDATA% (Windows), HF_HOME.
Snapshot dosyasinda sadece yol/boyut/mtime vardir, icerik yoktur.
"""
import argparse
import json
import os
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):  # Windows konsolu cp1252 olabilir; Turkce cikti icin
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIO_EXT = {".wav", ".flac", ".mp3", ".ogg", ".opus", ".webm", ".m4a", ".aac", ".pcm", ".raw", ".npy", ".pt"}
SKIP_PARTS = {".venv", ".python", "site-packages", "__pycache__", "node_modules", ".git", "Microsoft", "Google",
              "Packages", "Temp1", "CrashDumps", "D3DSCache", "NVIDIA", "pip", "uv"}


def watch_dirs():
    dirs = [ROOT, Path(tempfile.gettempdir()), Path.home() / ".cache"]
    if os.environ.get("LOCALAPPDATA"):
        dirs.append(Path(os.environ["LOCALAPPDATA"]))
    if os.environ.get("HF_HOME"):
        dirs.append(Path(os.environ["HF_HOME"]))
    return [d for d in dirs if d.exists()]


def snapshot(max_depth=6):
    snap = {}
    for base in watch_dirs():
        base_depth = len(base.parts)
        for dirpath, dirnames, filenames in os.walk(base):
            p = Path(dirpath)
            if len(p.parts) - base_depth >= max_depth:
                dirnames[:] = []
            dirnames[:] = [d for d in dirnames if d not in SKIP_PARTS]
            for fn in filenames:
                fp = p / fn
                try:
                    st = fp.stat()
                except OSError:
                    continue
                snap[str(fp)] = [st.st_size, int(st.st_mtime)]
    return snap


def cmd_snapshot(a):
    s = snapshot()
    Path(a.out).write_text(json.dumps({"t": time.time(), "dirs": [str(d) for d in watch_dirs()], "files": s}))
    print(f"[audit] {len(s)} dosya kaydedildi -> {a.out}")


def cmd_diff(a):
    before = json.loads(Path(a.before).read_text())
    now = snapshot()
    new = [(p, v) for p, v in now.items() if p not in before["files"]]
    changed = [(p, v) for p, v in now.items() if p in before["files"] and before["files"][p] != v]
    audio_like = [(p, v) for p, v in new + changed if Path(p).suffix.lower() in AUDIO_EXT]
    big = [(p, v) for p, v in new + changed if v[0] > 1_000_000 and Path(p).suffix.lower() not in AUDIO_EXT]
    print(f"[audit] izlenen: {', '.join(before['dirs'])}")
    print(f"[audit] yeni dosya: {len(new)}, degisen: {len(changed)}")
    print(f"[audit] SES UZANTILI yeni/degisen dosya: {len(audio_like)}")
    for p, v in audio_like:
        print(f"    !! {p}  ({v[0]} B)")
    print(f"[audit] 1 MB ustu diger yeni/degisen dosya: {len(big)}")
    for p, v in big[:30]:
        print(f"    - {p}  ({v[0]//1024} KB)")
    if a.verbose:
        for p, v in (new + changed)[:200]:
            print(f"    . {p}  ({v[0]} B)")
    return 1 if audio_like else 0


def cmd_connections(a):
    pids = {int(a.pid)}
    if sys.platform == "win32":
        # alt surecler
        out = subprocess.check_output(["wmic", "process", "get", "ProcessId,ParentProcessId"], text=True, errors="ignore") \
            if False else subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId | ConvertTo-Json -Compress"],
            text=True)
        procs = json.loads(out)
        changed = True
        while changed:
            changed = False
            for pr in procs:
                if pr["ParentProcessId"] in pids and pr["ProcessId"] not in pids:
                    pids.add(pr["ProcessId"]); changed = True
        ps = ("Get-NetTCPConnection | Where-Object { $_.OwningProcess -in @(" + ",".join(map(str, pids)) + ") } | "
              "Select-Object LocalAddress,LocalPort,RemoteAddress,RemotePort,State,OwningProcess | Format-Table -AutoSize | Out-String -Width 200")
        print(subprocess.check_output(["powershell", "-NoProfile", "-Command", ps], text=True))
    else:
        print(subprocess.run(["ss", "-tnp"], capture_output=True, text=True).stdout)
    print(f"[audit] incelenen PID'ler: {sorted(pids)}")
    print("[audit] beklenen: sadece 127.0.0.1:<port> LISTEN ve 127.0.0.1 <-> 127.0.0.1 ESTABLISHED. "
          "Dis IP'ye ESTABLISHED varsa (model indirme haric) sorun.")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s1 = sub.add_parser("snapshot"); s1.add_argument("--out", required=True)
    s2 = sub.add_parser("diff"); s2.add_argument("--before", required=True); s2.add_argument("--verbose", action="store_true")
    s3 = sub.add_parser("connections"); s3.add_argument("--pid", required=True)
    a = ap.parse_args()
    return {"snapshot": cmd_snapshot, "diff": cmd_diff, "connections": cmd_connections}[a.cmd](a) or 0


if __name__ == "__main__":
    sys.exit(main())
