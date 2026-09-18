#!/usr/bin/env python
"""bench: secili profil icin tepe VRAM ve gecikme olcumu (tekrar calistirilabilir).

Ne yapar:
  1. (varsayilan) server.py'yi secili profille ayri surec olarak baslatir, /health bekler
  2. nvidia-smi ile toplam VRAM kullanimini 0.5 s'de bir orneklerek tepe degeri bulur
     (Windows WDDM surec bazli VRAM vermez; olculen = sistem toplaminin baslangica gore artisi)
  3. test sesini BELLEKTE 16 kHz mono int16 PCM'e cevirir ve gercek zamanli hizda websocket'e gonderir
     (tarayicinin AudioWorklet'i ile ayni protokol). Ses diske yazilmaz, sunucu tarafinda da yazilmaz.
  4. gelen mesajlardan gecikme metriklerini cikarir:
       - first_text_s   : ilk metin gorunene kadar gecen sure (ses basindan itibaren)
       - commit_lag_s   : onaylanmis satirlarin (lines) sesin o anki konumuna gore gecikmesi (medyan / p90)
       - final_lag_s    : son ses ornegi gonderildikten sonra transkriptin kesinlesmesine kadar gecen sure
       - server_remaining_time : WLK'nin kendi bildirdigi isleme gecikmesi (medyan / maks)
  5. istege bagli sessizlik testi: ses bittikten sonra N saniye sifir PCM gonderir; bu surede yeni metin
     uretilirse VAD hatasi olarak raporlar
  6. istege bagli WER: --ref-text verilirse kelime hata orani

Kullanim:
  python tools/bench.py --profile dev-6gb --audio test.wav [--ref-text "..."] [--silence-seconds 20]
  python tools/bench.py --profile dev-6gb --audio test.wav --no-server --url ws://127.0.0.1:8000/asr
Sonuc: bench-results/<profil>-<zaman>.json (icinde ses yok; sadece metrikler ve son transkript metni)
"""
import argparse
import asyncio
import json
import os
import re
import shutil
import statistics
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):  # Windows konsolu cp1252 olabilir; Turkce cikti icin
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import threading
import time
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.config import load_config, resolve_profile  # noqa: E402

SR = 16000


def to_seconds(v):
    """WLK satir zamanlari '0:00:12.66' string'i ya da sayi olabilir."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        parts = str(v).strip().split(":")
        sec = 0.0
        for p in parts:
            sec = sec * 60 + float(p)
        return sec
    except ValueError:
        return None


# ----------------------------------------------------------------------------- VRAM
class VramSampler(threading.Thread):
    def __init__(self, interval=0.5):
        super().__init__(daemon=True)
        self.interval = interval
        self.samples = []
        self._stop = threading.Event()
        self.exe = shutil.which("nvidia-smi")

    def read(self):
        if not self.exe:
            return None
        try:
            out = subprocess.check_output([self.exe, "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                          text=True, timeout=5)
            return int(float(out.strip().splitlines()[0]))
        except Exception:  # noqa: BLE001
            return None

    def run(self):
        while not self._stop.is_set():
            v = self.read()
            if v is not None:
                self.samples.append((time.time(), v))
            self._stop.wait(self.interval)

    def stop(self):
        self._stop.set()


# ----------------------------------------------------------------------------- audio
def load_audio_pcm16(path):
    """Dosyayi bellekte 16 kHz mono int16'ya cevirir. Hicbir ara dosya yazmaz."""
    import soundfile as sf
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    if sr != SR:
        import soxr
        mono = soxr.resample(mono, sr, SR)
    mono = np.clip(mono, -1.0, 1.0)
    return (mono * 32767).astype(np.int16)


def wer(ref, hyp):
    norm = lambda s: re.sub(r"[^\w\s]", " ", s.lower(), flags=re.UNICODE).split()  # noqa: E731
    r, h = norm(ref), norm(hyp)
    d = np.zeros((len(r) + 1, len(h) + 1), dtype=int)
    d[:, 0] = np.arange(len(r) + 1)
    d[0, :] = np.arange(len(h) + 1)
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + (r[i - 1] != h[j - 1]))
    return d[len(r), len(h)] / max(1, len(r))


# ----------------------------------------------------------------------------- server
def start_server(profile, port, force, ssl_on=False):
    py = sys.executable
    cmd = [py, str(ROOT / "server.py"), "--profile", profile] + (["--force"] if force else [])
    env = dict(os.environ)
    proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env)
    url = f"{'https' if ssl_on else 'http'}://127.0.0.1:{port}/health"
    ctx = None
    if ssl_on:
        import ssl as _ssl
        ctx = _ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = _ssl.CERT_NONE
    t0 = time.time()
    while time.time() - t0 < 600:
        if proc.poll() is not None:
            raise SystemExit(f"sunucu cikti (kod {proc.returncode}); VRAM kontrolunden gecmedi ya da hata verdi")
        try:
            with urllib.request.urlopen(url, timeout=2, context=ctx) as r:
                if r.status == 200:
                    return proc, time.time() - t0
        except Exception:  # noqa: BLE001
            time.sleep(1)
    proc.kill()
    raise SystemExit("sunucu 600 s icinde hazir olmadi")


def stop_server(proc):
    if proc is None:
        return
    try:
        if sys.platform == "win32":
            subprocess.call(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
        else:
            proc.terminate()
        proc.wait(timeout=20)
    except Exception:  # noqa: BLE001
        proc.kill()


# ----------------------------------------------------------------------------- stream
async def stream(url, pcm, chunk_s, silence_s, rt_factor, language):
    import websockets

    metrics = {"first_text_s": None, "commit_lags": [], "remaining": [], "msgs": 0,
               "silence_new_text": [], "final_lag_s": None, "text": "", "lines": []}
    chunk = int(SR * chunk_s)
    total_audio_s = len(pcm) / SR
    t0 = None
    last_change = {"t": None, "text": ""}
    seen_line_ends = {}   # line idx -> (end, text) son gorulen
    silence_phase = {"on": False, "start_t": None, "base_text": ""}
    audio_pos = {"s": 0.0}
    stop = asyncio.Event()

    full_url = url + ("&" if "?" in url else "?") + f"language={language}"
    ssl_ctx = None
    if full_url.startswith("wss://"):
        import ssl as _ssl
        ssl_ctx = _ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = _ssl.CERT_NONE       # kendinden imzali sertifika (yerel ag testi)
    async with websockets.connect(full_url, max_size=None, ssl=ssl_ctx) as ws:
        async def receiver():
            try:
                await _receiver()
            except Exception as e:  # noqa: BLE001
                metrics["receiver_error"] = repr(e)
                print(f"[bench] alici hatasi: {e!r}")

        async def _receiver():
            async for raw in ws:
                now = time.time()
                try:
                    d = json.loads(raw)
                except Exception:  # noqa: BLE001
                    continue
                if d.get("type") == "config":
                    continue
                if d.get("type") == "ready_to_stop":
                    stop.set()
                    return
                metrics["msgs"] += 1
                lines = d.get("lines") or []
                text_lines = [ln.get("text", "") for ln in lines if ln.get("speaker") != -2]
                text = " ".join(t for t in text_lines if t).strip()
                buf = (d.get("buffer_transcription") or "").strip()
                combined = (text + " " + buf).strip()
                if combined and metrics["first_text_s"] is None and t0:
                    metrics["first_text_s"] = now - t0
                if combined != last_change["text"]:
                    last_change["text"] = combined
                    last_change["t"] = now
                    if silence_phase["on"] and combined != silence_phase["base_text"]:
                        metrics["silence_new_text"].append({"t_after_silence_start": now - silence_phase["start_t"],
                                                            "text": combined[-120:]})
                for i, ln in enumerate(lines):
                    if ln.get("speaker") == -2 or not ln.get("text"):
                        continue
                    key = (ln.get("end"), ln.get("text"))
                    end_s = to_seconds(ln.get("end"))
                    if seen_line_ends.get(i) != key and end_s is not None and t0:
                        seen_line_ends[i] = key
                        # satirin kapsadigi sesin bitisine gore ne kadar geride gorunuyor
                        lag = now - (t0 + end_s / rt_factor)
                        if 0 <= lag < 120:
                            metrics["commit_lags"].append(lag)
                rt = d.get("remaining_time_transcription")
                if isinstance(rt, (int, float)) and not silence_phase["on"] and not audio_pos.get("done"):
                    metrics["remaining"].append(float(rt))   # sadece ses akarken (sessizlikte VAD atladigi icin sayac buyur)
                metrics["text"] = text
                metrics["buffer"] = buf
                metrics["lines"] = lines

        recv_task = asyncio.create_task(receiver())
        t0 = time.time()
        # gercek zamanli gonderim
        for start in range(0, len(pcm), chunk):
            piece = pcm[start:start + chunk]
            await ws.send(piece.tobytes())
            audio_pos["s"] = (start + len(piece)) / SR
            target = t0 + audio_pos["s"] / rt_factor
            delay = target - time.time()
            if delay > 0:
                await asyncio.sleep(delay)
        t_audio_end = time.time()
        audio_pos["done"] = True
        # sessizlik (VAD testi)
        if silence_s > 0:
            silence_phase.update({"on": True, "start_t": time.time(), "base_text": last_change["text"]})
            zeros = np.zeros(chunk, dtype=np.int16).tobytes()
            n = int(silence_s / chunk_s)
            for i in range(n):
                await ws.send(zeros)
                await asyncio.sleep(chunk_s / rt_factor)
            silence_phase["on"] = False
        # bitis: bos mesaj -> sunucu kalan tamponu kesinlestirir ve ready_to_stop gonderir
        await ws.send(b"")
        try:
            await asyncio.wait_for(stop.wait(), timeout=120)
        except asyncio.TimeoutError:
            metrics["note"] = "ready_to_stop 120 s icinde gelmedi"
        recv_task.cancel()
        if last_change["t"]:
            metrics["final_lag_s"] = max(0.0, last_change["t"] - t_audio_end)
        metrics["audio_s"] = total_audio_s
        metrics["wall_s"] = time.time() - t0
    return metrics


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile")
    ap.add_argument("--config")
    ap.add_argument("--audio", required=True, help="test ses dosyasi (wav/flac/ogg...). Bellekte 16k mono'ya cevrilir")
    ap.add_argument("--ref-text", default=None, help="WER icin referans metin")
    ap.add_argument("--silence-seconds", type=float, default=0.0, help="ses bitince gonderilecek sessizlik (VAD testi)")
    ap.add_argument("--chunk-seconds", type=float, default=0.1)
    ap.add_argument("--realtime-factor", type=float, default=1.0, help="1.0 = gercek zaman; 2.0 = iki kat hizli gonder")
    ap.add_argument("--no-server", action="store_true", help="sunucuyu baslatma, --url'e baglan")
    ap.add_argument("--url", default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--out-dir", default=str(ROOT / "bench-results"))
    a = ap.parse_args()

    cfg = load_config(a.config)
    prof = resolve_profile(cfg, a.profile)
    s = cfg["server"]
    port = int(s.get("port", 8000))
    ssl_on = bool((s.get("ssl") or {}).get("enabled"))
    url = a.url or f"{'wss' if ssl_on else 'ws'}://127.0.0.1:{port}/asr"
    language = s.get("language", "tr")

    pcm = load_audio_pcm16(a.audio)
    print(f"[bench] profil={prof['name']} model={prof['model']} backend={prof.get('backend')} "
          f"policy={prof.get('policy')} compute_type={prof.get('compute_type')} diarization={prof.get('diarization')}")
    print(f"[bench] ses: {len(pcm)/SR:.1f} s, sessizlik testi: {a.silence_seconds:.0f} s")

    sampler = VramSampler()
    base = sampler.read()
    sampler.start()
    proc = None
    startup_s = None
    try:
        if not a.no_server:
            proc, startup_s = start_server(prof["name"], port, a.force, ssl_on)
            print(f"[bench] sunucu hazir ({startup_s:.1f} s)")
            time.sleep(2)
        after_load = sampler.read()
        m = asyncio.run(stream(url, pcm, a.chunk_seconds, a.silence_seconds, a.realtime_factor, language))
        time.sleep(1)
    finally:
        sampler.stop()
        stop_server(proc)

    used = [v for _, v in sampler.samples]
    peak = max(used) if used else None
    res = {
        "profile": prof["name"], "model": prof["model"], "backend": prof.get("backend"), "policy": prof.get("policy"),
        "compute_type": prof.get("compute_type"), "diarization": bool(prof.get("diarization")),
        "diarization_device": prof.get("diarization_device"),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "vram_baseline_mb": base, "vram_after_model_load_mb": after_load, "vram_peak_total_mb": peak,
        "vram_peak_delta_mb": (peak - base) if (peak is not None and base is not None) else None,
        "vram_model_delta_mb": (after_load - base) if (after_load is not None and base is not None) else None,
        "startup_s": startup_s,
        "audio_s": m.get("audio_s"), "wall_s": m.get("wall_s"),
        "first_text_s": m.get("first_text_s"),
        "commit_lag_median_s": statistics.median(m["commit_lags"]) if m["commit_lags"] else None,
        "commit_lag_p90_s": (sorted(m["commit_lags"])[int(0.9 * (len(m["commit_lags"]) - 1))]
                             if m["commit_lags"] else None),
        "server_remaining_median_s": statistics.median(m["remaining"]) if m["remaining"] else None,
        "server_remaining_max_s": max(m["remaining"]) if m["remaining"] else None,
        "final_lag_s": m.get("final_lag_s"),
        "messages": m.get("msgs"),
        "silence_seconds": a.silence_seconds,
        "silence_new_text_events": m.get("silence_new_text"),
        "transcript": (m.get("text", "") + " " + m.get("buffer", "")).strip(),
        "note": m.get("note"),
    }
    if a.ref_text:
        res["wer"] = round(wer(a.ref_text, res["transcript"]), 3)

    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{prof['name']}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

    def f(v, unit=""):
        return "-" if v is None else (f"{v:.2f}{unit}" if isinstance(v, float) else f"{v}{unit}")

    print("\n== sonuc ==")
    print(f"  VRAM: baslangic {f(base,' MB')}  model yuklu {f(after_load,' MB')}  tepe {f(peak,' MB')}  "
          f"-> sunucu tepe farki {f(res['vram_peak_delta_mb'],' MB')}")
    print(f"  baslangic suresi: {f(startup_s,' s')}   ilk metin: {f(res['first_text_s'],' s')}")
    print(f"  onayli metin gecikmesi: medyan {f(res['commit_lag_median_s'],' s')}  p90 {f(res['commit_lag_p90_s'],' s')}")
    print(f"  sunucu bildirdigi isleme gecikmesi: medyan {f(res['server_remaining_median_s'],' s')}  "
          f"maks {f(res['server_remaining_max_s'],' s')}")
    print(f"  son ses -> kesinlesme: {f(res['final_lag_s'],' s')}")
    if a.silence_seconds > 0:
        ev = res["silence_new_text_events"] or []
        # ilk 5 s: ses bitmeden once tamponda kalan metnin kesinlesmesi (normal). Sonrasi: sessizlikte uretilen metin.
        late = [e for e in ev if e["t_after_silence_start"] > 5.0]
        res["silence_hallucination_events"] = late
        print(f"  sessizlik testi ({a.silence_seconds:.0f} s): ilk 5 s'de {len(ev)-len(late)} kesinlestirme, "
              f"sonrasinda {'metin degismedi (OK)' if not late else f'{len(late)} metin degisikligi (UYARI: transkriptle karsilastir - gecikmis kesinlestirme mi, uydurma mi?)'}")
        for e in late[:5]:
            print(f"     +{e['t_after_silence_start']:.1f}s: ...{e['text']}")
        out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    if "wer" in res:
        print(f"  WER: {res['wer']*100:.1f}%")
    print(f"  transkript: {res['transcript'][:400]}")
    print(f"  kayit: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
