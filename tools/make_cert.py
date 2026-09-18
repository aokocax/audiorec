#!/usr/bin/env python
"""Yerel ag icin kendinden imzali TLS sertifikasi uretir (certs/audiorec.crt + audiorec.key).

Tarayicilar mikrofona sadece localhost ya da HTTPS uzerinden izin verir; LAN'dan baglanmak icin HTTPS sart.
SAN listesi: hostname, localhost, 127.0.0.1 ve makinenin butun IPv4 adresleri (+ --extra ile verilenler).
Istemci tarayicida ilk girişte "guvenilmeyen sertifika" uyarisi cikar; kabul edilir ya da certs/audiorec.crt
istemciye "Guvenilen Kok" olarak yuklenir (README). Internet'e hicbir sey gitmez.

Kullanim: python tools/make_cert.py [--days 825] [--extra 192.168.1.50 --extra sunucu.local] [--force]
"""
import argparse
import datetime as dt
import ipaddress
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def local_ipv4s():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except socket.gaierror:
        pass
    try:  # varsayilan rota uzerindeki adres (baglanti kurulmaz, sadece soket secimi)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=str(ROOT / "certs"))
    ap.add_argument("--days", type=int, default=825)
    ap.add_argument("--extra", action="append", default=[], help="ek IP ya da DNS adi (tekrarlanabilir)")
    ap.add_argument("--force", action="store_true", help="var olan sertifikayi uzerine yaz")
    a = ap.parse_args()

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    crt, key = out / "audiorec.crt", out / "audiorec.key"
    if crt.exists() and not a.force:
        print(f"[cert] zaten var: {crt}  (yenilemek icin --force)")
        return 0

    host = socket.gethostname()
    names = {host, host.lower(), "localhost"}
    ips = {"127.0.0.1"} | set(local_ipv4s())
    for e in a.extra:
        try:
            ipaddress.ip_address(e)
            ips.add(e)
        except ValueError:
            names.add(e)
    san = [x509.DNSName(n) for n in sorted(names)] + [x509.IPAddress(ipaddress.ip_address(i)) for i in sorted(ips)]

    priv = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"audiorec @ {host}")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(subject).issuer_name(subject).public_key(priv.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=a.days))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(priv, hashes.SHA256()))
    key.write_bytes(priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    try:
        key.chmod(0o600)
    except OSError:
        pass
    print(f"[cert] yazildi: {crt}, {key}")
    print(f"[cert] SAN: {', '.join(sorted(names))}, {', '.join(sorted(ips))}")
    print(f"[cert] gecerlilik: {a.days} gun. Istemcilerde guvenilir yapmak icin certs/audiorec.crt dosyasini kullan.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
