"""Ручная сборка APK «Лилит: Новелла» без Android SDK (офлайн-окружение).

Цепочка:
  Java-код (MainActivity.smali) -> smali.jar -> classes.dex
  AndroidManifest.xml (бинарный AXML, генератор ниже)
  web-приложение (novel_app/web, фото конвертируются в JPEG)
  zip-упаковка -> jarsigner (JDK из jdk4py) -> LilithNovel.apk

Запуск:
  python3 scripts/build_apk_manual.py
"""

from __future__ import annotations

import io
import json
import os
import shutil
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.novel import SCENARIOS  # noqa: E402

OUT = ROOT / "novel_app" / "LilithNovel.apk"
WORK = ROOT / "novel_app" / "build_tmp"

# Пути инструментов
JAVA_HOME = None
try:
    import jdk4py  # type: ignore

    JAVA_HOME = Path(jdk4py.JAVA_HOME)
except Exception:
    pass
SMALI_JAR = Path("/tmp/apktools/rc_repo/bin/smali.jar")


# =====================================================================
# 1. Генератор бинарного AndroidManifest.xml (AXML)
# =====================================================================

def uleb128(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


class StringPool:
    def __init__(self) -> None:
        self.strings: list[str] = []
        self.index: dict[str, int] = {}

    def add(self, s: str) -> int:
        if s not in self.index:
            self.index[s] = len(self.strings)
            self.strings.append(s)
        return self.index[s]

    def build(self) -> bytes:
        data = bytearray()
        offsets: list[int] = []
        for s in self.strings:
            raw = s.encode("utf-8")
            utf16_len = len(s.encode("utf-16-le")) // 2
            offsets.append(len(data))
            # Формат ResStringPool (UTF-8): [utf16len][utf8len][bytes]0x00 + pad до 4
            data += uleb128(utf16_len)
            data += uleb128(len(raw))
            data += raw
            data += b"\x00"
            while len(data) % 4:
                data += b"\x00"
        n = len(self.strings)
        header = struct.pack("<HHIIIIII", 0x0001, 28, 28 + 4 * n + len(data),
                             n, 0, 0x00000100, 28 + 4 * n, 0)
        body = b"".join(struct.pack("<I", o) for o in offsets) + bytes(data)
        return header + body


class AXMLWriter:
    """Пишет бинарный Android XML (минимальный, без ресурсов)."""

    def __init__(self) -> None:
        self.sp = StringPool()
        self.res_ids: list[int] = []

    def _chunk(self, ctype: int, body: bytes, hsize: int = 16, line: int = 1) -> bytes:
        return struct.pack("<HHI", ctype, hsize, hsize + len(body)) + struct.pack(
            "<II", line, 0
        ) + body if hsize == 16 else struct.pack("<HHI", ctype, hsize, hsize + len(body)) + body

    # ---------------------------------------------------------------- элементы

    def build(self, root: dict) -> bytes:
        """root: дерево {tag, ns, attrs:[(ns, name, value, type, data)], children:[]}"""
        # Сначала регистрируем ВСЕ строки
        chunks = bytearray()

        def reg_node(node: dict) -> None:
            self.sp.add(node["tag"])
            if node.get("ns"):
                self.sp.add(node["ns"])
            for ns, name, _v, _t, _d in node.get("attrs", []):
                if ns:
                    self.sp.add(ns)
                self.sp.add(name)

        def walk(node: dict) -> None:
            reg_node(node)
            for c in node.get("children", []):
                walk(c)

        walk(root)

        # Значения атрибутов тоже регистрируем ДО построения пула
        def reg_values(node: dict) -> None:
            for _ns, _name, value, _t, _d in node.get("attrs", []):
                if value is not None:
                    self.sp.add(str(value))
            for c in node.get("children", []):
                reg_values(c)

        reg_values(root)
        # namespace uri + префикс
        self.sp.add("http://schemas.android.com/apk/res/android")
        self.sp.add("android")
        # ресурс-мапа
        for node_holder in ([root] + list(_flatten(root))):
            for ns, name, _v, _t, _d in node_holder.get("attrs", []):
                if name in _RES_IDS:
                    rid = _RES_IDS[name]
                    if rid not in self.res_ids:
                        self.res_ids.append(rid)

        chunks += self.sp.build()
        # resource map chunk
        rm = struct.pack("<HHI", 0x0180, 8, 8 + 4 * len(self.res_ids))
        rm += b"".join(struct.pack("<I", r) for r in self.res_ids)
        chunks += rm

        # namespace start (android)
        ns_uri = self.sp.index["http://schemas.android.com/apk/res/android"]
        ns_prefix = self.sp.index["android"]
        chunks += struct.pack("<HHIIIII", 0x0100, 16, 24, 1, 0xFFFFFFFF, ns_prefix, ns_uri)

        def emit(node: dict) -> None:
            nonlocal chunks
            tag_i = self.sp.index[node["tag"]]
            ns_i = self.sp.index[node["ns"]] if node.get("ns") else 0xFFFFFFFF
            attrs = node.get("attrs", [])
            n_attrs = len(attrs)
            body = struct.pack("<IIHHHHHH", ns_i, tag_i, 20, 20, n_attrs, 0, 0, 0)
            for ns, name, value, vtype, data in attrs:
                a_ns = self.sp.index[ns] if ns else 0xFFFFFFFF
                a_name = self.sp.index[name]
                rid = _RES_IDS.get(name, 0)
                if value is not None:
                    raw = self.sp.index.get(str(value), 0xFFFFFFFF)
                else:
                    raw = 0xFFFFFFFF
                # ВАЖНО: для строковых атрибутов typedValue.data = индекс строки
                # (как и raw). Иначе Android читает неверные значения и
                # package теряется -> «не удалось обработать пакет».
                if vtype == TYPE_STRING and raw != 0xFFFFFFFF:
                    data = raw
                tv = struct.pack("<HBB", 8, 0, vtype) + struct.pack("<I", data)
                body += struct.pack("<III", a_ns, a_name, raw) + tv
            chunks += struct.pack("<HHIII", 0x0102, 16, 16 + len(body), 1, 0) + body
            for c in node.get("children", []):
                emit(c)
            chunks += struct.pack("<HHIIIII", 0x0103, 16, 24, 1, 0xFFFFFFFF, ns_i, tag_i)

        emit(root)
        chunks += struct.pack("<HHIIIII", 0x0101, 16, 24, 1, 0xFFFFFFFF, ns_prefix, ns_uri)

        header = struct.pack("<HHI", 0x0003, 8, 8 + len(chunks))
        return header + bytes(chunks)


def _flatten(node: dict):
    for c in node.get("children", []):
        yield c
        yield from _flatten(c)


# Resource ID атрибутов android: (из public.xml)
_RES_IDS = {
    "theme": 0x01010000,
    "label": 0x01010001,
    "icon": 0x01010002,
    "name": 0x01010003,
    "exported": 0x01010010,
    "allowBackup": 0x01010280,
    "versionCode": 0x0101021b,
    "versionName": 0x0101021c,
}

# Типы значений
TYPE_STRING = 0x03
TYPE_INT_DEC = 0x10
TYPE_INT_BOOLEAN = 0x12
TYPE_REFERENCE = 0x01


def build_manifest() -> bytes:
    w = AXMLWriter()
    root = {
        "tag": "manifest",
        "attrs": [
            (None, "package", "com.lilith.novel", TYPE_STRING, 0),
            ("http://schemas.android.com/apk/res/android", "versionCode",
             "1", TYPE_INT_DEC, 1),
            ("http://schemas.android.com/apk/res/android", "versionName",
             "1.0.0", TYPE_STRING, 0),
        ],
        "children": [
            {
                "tag": "uses-sdk",
                "attrs": [
                    ("http://schemas.android.com/apk/res/android", "minSdkVersion",
                     "21", TYPE_INT_DEC, 21),
                    ("http://schemas.android.com/apk/res/android", "targetSdkVersion",
                     "28", TYPE_INT_DEC, 28),
                ],
                "children": [],
            },
            {
                "tag": "application",
                "attrs": [
                    ("http://schemas.android.com/apk/res/android", "label",
                     "Лилит: Новелла", TYPE_STRING, 0),
                    ("http://schemas.android.com/apk/res/android", "allowBackup",
                     "true", TYPE_INT_BOOLEAN, 0xFFFFFFFF),
                ],
                "children": [
                    {
                        "tag": "activity",
                        "attrs": [
                            ("http://schemas.android.com/apk/res/android", "name",
                             ".MainActivity", TYPE_STRING, 0),
                            ("http://schemas.android.com/apk/res/android", "exported",
                             "true", TYPE_INT_BOOLEAN, 0xFFFFFFFF),
                        ],
                        "children": [
                            {
                                "tag": "intent-filter",
                                "attrs": [],
                                "children": [
                                    {"tag": "action", "attrs": [
                                        ("http://schemas.android.com/apk/res/android", "name",
                                         "android.intent.action.MAIN", TYPE_STRING, 0)],
                                     "children": []},
                                    {"tag": "category", "attrs": [
                                        ("http://schemas.android.com/apk/res/android", "name",
                                         "android.intent.category.LAUNCHER", TYPE_STRING, 0)],
                                     "children": []},
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    return w.build(root)


# =====================================================================
# 2. Сборка
# =====================================================================

MAIN_SMALI = """\
.class public Lcom/lilith/novel/MainActivity;
.super Landroid/app/Activity;

.field private webView:Landroid/webkit/WebView;

.method public constructor <init>()V
    .registers 1

    invoke-direct {p0}, Landroid/app/Activity;-><init>()V

    return-void
.end method

.method protected onCreate(Landroid/os/Bundle;)V
    .registers 8

    invoke-super {p0, p1}, Landroid/app/Activity;->onCreate(Landroid/os/Bundle;)V

    new-instance v0, Landroid/webkit/WebView;
    invoke-direct {v0, p0}, Landroid/webkit/WebView;-><init>(Landroid/content/Context;)V
    iput-object v0, p0, Lcom/lilith/novel/MainActivity;->webView:Landroid/webkit/WebView;

    invoke-virtual {v0}, Landroid/webkit/WebView;->getSettings()Landroid/webkit/WebSettings;
    move-result-object v1

    const/4 v2, 0x1
    invoke-virtual {v1, v2}, Landroid/webkit/WebSettings;->setJavaScriptEnabled(Z)V
    invoke-virtual {v1, v2}, Landroid/webkit/WebSettings;->setDomStorageEnabled(Z)V
    invoke-virtual {v1, v2}, Landroid/webkit/WebSettings;->setAllowFileAccess(Z)V
    invoke-virtual {v1, v2}, Landroid/webkit/WebSettings;->setAllowContentAccess(Z)V
    invoke-virtual {v1, v2}, Landroid/webkit/WebSettings;->setLoadWithOverviewMode(Z)V
    invoke-virtual {v1, v2}, Landroid/webkit/WebSettings;->setUseWideViewPort(Z)V

    new-instance v3, Landroid/webkit/WebViewClient;
    invoke-direct {v3}, Landroid/webkit/WebViewClient;-><init>()V
    invoke-virtual {v0, v3}, Landroid/webkit/WebView;->setWebViewClient(Landroid/webkit/WebViewClient;)V

    const-string v4, "file:///android_asset/novel/index.html"
    invoke-virtual {v0, v4}, Landroid/webkit/WebView;->loadUrl(Ljava/lang/String;)V

    invoke-virtual {p0, v0}, Landroid/app/Activity;->setContentView(Landroid/view/View;)V

    return-void
.end method

.method public onKeyDown(ILandroid/view/KeyEvent;)Z
    .registers 6

    const/4 v0, 0x4
    if-ne p1, v0, :cond_default

    iget-object v1, p0, Lcom/lilith/novel/MainActivity;->webView:Landroid/webkit/WebView;
    if-eqz v1, :cond_default
    invoke-virtual {v1}, Landroid/webkit/WebView;->canGoBack()Z
    move-result v2
    if-eqz v2, :cond_default

    invoke-virtual {v1}, Landroid/webkit/WebView;->goBack()V
    const/4 v0, 0x1
    return v0

    :cond_default
    invoke-super {p0, p1, p2}, Landroid/app/Activity;->onKeyDown(ILandroid/view/KeyEvent;)Z
    move-result v0
    return v0
.end method
"""


def run(cmd: list[str]) -> None:
    print(">", " ".join(str(c) for c in cmd)[:120])
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-2000:])
        print(r.stderr[-2000:])
        raise SystemExit(f"Ошибка: {cmd[0]}")


def build_web_assets(work: Path) -> None:
    """Собирает web-приложение: ВСЕ фото галереи + сценарии (JPEG)."""
    from PIL import Image  # type: ignore

    web = work / "novel"
    (web / "images").mkdir(parents=True, exist_ok=True)

    # ВСЕ фото из assets/gallery -> JPEG (и для сцен, и для галереи)
    gallery_names: list[str] = []
    for src in sorted((ROOT / "assets" / "gallery").glob("*.png")):
        jpg = src.stem + ".jpg"
        dst = web / "images" / jpg
        if not dst.exists():
            im = Image.open(src).convert("RGB")
            im.thumbnail((1080, 1920), Image.LANCZOS)
            im.save(dst, "JPEG", quality=82, optimize=True)
        gallery_names.append(jpg)

    # сценарии (46 фото — подмножество всех)
    payload: dict = {"scenarios": {}}
    for sid, sc in SCENARIOS.items():
        nodes = {}
        for nid, node in sc["nodes"].items():
            n = dict(node)
            n["image"] = node["image"].replace(".png", ".jpg")
            nodes[nid] = n
        payload["scenarios"][sid] = {
            "title": sc["title"], "subtitle": sc["subtitle"],
            "start": sc["start"], "nodes": nodes,
        }

    js = "window.NOVEL_DATA = " + json.dumps(payload, ensure_ascii=False, indent=1) + ";\n"
    (web / "scenarios.js").write_text(js, encoding="utf-8")
    # галерея: список ВСЕХ фото (серия определяется по префиксу имени)
    gj = "window.GALLERY = " + json.dumps(gallery_names, ensure_ascii=False) + ";\n"
    (web / "gallery.js").write_text(gj, encoding="utf-8")
    # статика
    for f in ("index.html", "style.css", "app.js"):
        shutil.copy2(ROOT / "novel_app" / "web" / f, web / f)
    total = sum(f.stat().st_size for f in (web / "images").glob("*"))
    n = len(list((web / "images").glob("*")))
    print(f"web-ассеты: {n} фото, {total//1024//1024} МБ")


def _make_key_cert():
    """Создаёт RSA-ключ и самоподписанный сертификат."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Lilith Novel")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime_now_utc())
        .not_valid_after(datetime_now_utc_plus_years(27))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return key, cert


def sign_v1(apk: Path) -> tuple:
    """JAR-подпись APK (схема v1) — как делает jarsigner, но на Python.

    Возвращает (key, cert) для последующей подписи v2.
    """
    import base64
    import hashlib

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key, cert = _make_key_cert()
    """JAR-подпись APK (схема v1) — как делает jarsigner, но на Python.

    Генерирует RSA-ключ + самоподписанный сертификат (cryptography),
    собирает META-INF/MANIFEST.MF, META-INF/CERT.SF и PKCS#7 CERT.RSA.
    """
    import base64
    import hashlib

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    # 1. Читаем файлы APK (кроме META-INF)
    entries: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(apk) as z:
        for info in z.infolist():
            if info.filename.startswith("META-INF/"):
                continue
            if info.filename.endswith("/"):
                continue
            entries.append((info.filename, z.read(info.filename)))
    entries.sort(key=lambda e: e[0])

    def b64sha1(data: bytes) -> str:
        return base64.b64encode(hashlib.sha256(data).digest()).decode()

    # 3. MANIFEST.MF
    # ВАЖНО: секции в MANIFEST.MF и диджесты секций в CERT.SF должны
    # СОВПАДАТЬ байт-в-байт. Раньше в MF писалось SHA-256-Digest, а секция
    # для CERT.SF содержала SHA1-Digest — Android видел несовпадение и
    # отклонял пакет. Теперь обе части используют ОДНУ строку section.
    sections: dict[str, str] = {}
    mf_parts = ["Manifest-Version: 1.0", "Created-By: 1.0 (Lilith)"]
    for path, data in entries:
        section = f"Name: {path}\r\nSHA-256-Digest: {b64sha1(data)}\r\n\r\n"
        sections[path] = section
        mf_parts.append("")
        mf_parts.append(f"Name: {path}")
        mf_parts.append(f"SHA-256-Digest: {b64sha1(data)}")
    manifest_mf = "\r\n".join(mf_parts) + "\r\n"
    manifest_body = manifest_mf

    # 4. CERT.SF
    sf_lines = [
        "Signature-Version: 1.0",
        "Created-By: 1.0 (Lilith)",
        f"SHA-256-Digest-Manifest: {b64sha1(manifest_body.encode('utf-8'))}",
    ]
    for path in dict.fromkeys(p for p, _ in entries):
        sf_lines.append("")
        sf_lines.append(f"Name: {path}")
        sf_lines.append(f"SHA-256-Digest: {b64sha1(sections[path].encode('utf-8'))}")
    cert_sf = "\r\n".join(sf_lines) + "\r\n"

    # 5. CERT.RSA — PKCS#7 SignedData над CERT.SF
    from cryptography.hazmat.primitives.serialization import Encoding, pkcs7

    rsa_der = (
        pkcs7.PKCS7SignatureBuilder()
        .set_data(cert_sf.encode("utf-8"))
        .add_signer(cert, key, hashes.SHA256())
        .sign(Encoding.DER, [pkcs7.PKCS7Options.Binary])
    )

    # 6. Пересобираем APK с META-INF
    tmp = apk.with_suffix(".unsigned.apk")
    apk.rename(tmp)
    with zipfile.ZipFile(apk, "w", zipfile.ZIP_STORED) as z:
        for path, data in entries:
            z.writestr(path, data)
        z.writestr("META-INF/MANIFEST.MF", manifest_mf)
        z.writestr("META-INF/CERT.SF", cert_sf)
        z.writestr("META-INF/CERT.RSA", rsa_der)
    tmp.unlink()
    return key, cert



def sign_v2(apk: Path, key, cert) -> None:
    """APK Signature Scheme v2 (обязательна для Android 7.0+ / Android 11+).

    Вставляет APK Signing Block перед central directory и пересчитывает
    смещение каталога в EOCD. Подпись — RSA-PKCS1v1.5-SHA256 (algo 0x0103).
    Длина блока фиксирована (RSA-2048 -> подпись 256 байт), поэтому:
    патчим EOCD offset -> считаем диджесты -> подписываем -> вставляем.
    """
    import hashlib

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    ALG = 0x0103  # RSASSA-PKCS1-v1_5 with SHA-256
    ID_SIG = 0x7109871A
    MAGIC = b"APK Sig Block 42"

    data = apk.read_bytes()
    eocd_pos = data.rfind(b"PK\x05\x06")
    if eocd_pos < 0:
        raise SystemExit("EOCD не найден")
    cd_offset = struct.unpack_from("<I", data, eocd_pos + 16)[0]

    def lp(b: bytes) -> bytes:
        return struct.pack("<I", len(b)) + b

    cert_der = cert.public_bytes(serialization.Encoding.DER)
    pubkey_der = key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    # --- Длина value/блока (не зависит от содержимого подписи) ---
    def block_len_for(sig_len: int) -> int:
        # signed data (без реальной подписи): digest 32 б, cert, sdks, attrs
        digest_len = 32
        digests_entry = struct.pack("<I", ALG) + lp(b"\x00" * digest_len)
        signed_len = len(lp(digests_entry)) + len(lp(cert_der)) + 8 + len(lp(b""))
        sig_entry_len = 4 + 4 + sig_len
        # signer = lp(signed) + lp(lp(sig_entry)) + lp(pubkey)
        signer_len = 4 + signed_len + 4 + 4 + sig_entry_len + 4 + len(pubkey_der)
        value_len = 4 + signer_len
        pairs_len = 8 + 4 + value_len
        # Полный размер блока: [size1(8)][pairs][size2(8)][magic(16)]
        return pairs_len + 8 + 8 + len(MAGIC)

    block_len = block_len_for(256)  # RSA-2048 -> 256 байт подписи

    # --- Патчим EOCD offset (на длину будущего блока) ---
    patched = bytearray(data)
    struct.pack_into("<I", patched, eocd_pos + 16, cd_offset + block_len)

    # --- Диджесты контента ПО ФИНАЛЬНОМУ содержимому (offset уже новый) ---
    seg1 = bytes(patched[:cd_offset])
    seg2 = bytes(patched[cd_offset:])
    d1 = hashlib.sha256(b"\xa5" + seg1).digest()
    d2 = hashlib.sha256(b"\xa5" + seg2).digest()
    digest = hashlib.sha256(d1 + d2).digest()

    # --- Signed data и подпись ---
    digests_entry = struct.pack("<I", ALG) + lp(digest)
    signed = lp(digests_entry) + lp(cert_der) + struct.pack("<II", 0xFFFFFFFF, 0xFFFFFFFF) + lp(b"")
    # По спецификации v2 подпись считается по signed-данным с префиксом
    # 0xA5 + uint32(длина): content = 0xA5 || len(signed) || signed.
    # Раньше подписывался сам signed без префикса — Android отклонял APK.
    sign_content = b"\xa5" + struct.pack("<I", len(signed)) + signed
    sig = key.sign(sign_content, padding.PKCS1v15(), hashes.SHA256())
    assert len(sig) == 256
    sig_entry = struct.pack("<I", ALG) + lp(sig)
    # signatures — это ПОСЛЕДОВАТЕЛЬНОСТЬ length-prefixed подписей
    signer = lp(signed) + lp(lp(sig_entry)) + lp(pubkey_der)
    value = lp(signer)

    # --- APK Signing Block ---
    # ВАЖНО: pair_len включает СВОЁ поле длины (8) + id (4) + value.
    # Раньше было 4 + len(value) — Android читал value на 8 байт короче,
    # подпись обрезалась -> «не удалось обработать пакет».
    pairs = struct.pack("<Q", 12 + len(value)) + struct.pack("<I", ID_SIG) + value
    size1 = len(pairs) + 8 + len(MAGIC)
    block = struct.pack("<Q", size1) + pairs + struct.pack("<Q", size1) + MAGIC
    assert len(block) == block_len, (len(block), block_len)

    # --- Финальная сборка ---
    final = bytearray()
    final += patched[:cd_offset]
    final += block
    final += patched[cd_offset:]
    apk.write_bytes(bytes(final))
    print(f"v2: APK Signing Block ({len(block)} б) + подпись RSA-SHA256, диджесты по финальному файлу")


def _sign_with_apksigner(apk: Path, java: Path) -> None:
    """Подписывает APK официальным apksigner (com.android.apksigner.ApkSignerTool).
    Создаёт keystore через keytool и подписывает v1+v2."""
    import subprocess as _sp

    keytool = JAVA_HOME / "bin" / "keytool"
    ks = WORK / "lilith.keystore"
    if not ks.exists():
        r = _sp.run([str(keytool), "-genkeypair", "-keystore", str(ks),
                     "-alias", "lilith", "-storepass", "lilith123", "-keypass", "lilith123",
                     "-dname", "CN=Lilith Novel", "-keyalg", "RSA", "-keysize", "2048",
                     "-validity", "10000", "-noprompt"], capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"keytool: {r.stderr[-500:]}")
    tmp = apk.with_suffix(".unsigned.apk")
    apk.rename(tmp)
    r = _sp.run([str(java), "-jar", "/tmp/apksigner.jar", "sign",
                 "--ks", str(ks), "--ks-pass", "pass:lilith123",
                 "--ks-key-alias", "lilith", "--key-pass", "pass:lilith123",
                 "--out", str(apk), str(tmp)], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"apksigner: {r.stdout[-800:]}\n{r.stderr[-800:]}")
    tmp.unlink()
    print("apksigner: подпись v1+v2 (официальная реализация apksig)")


def datetime_now_utc():
    from datetime import UTC, datetime

    return datetime.now(UTC)


def datetime_now_utc_plus_years(years: int):
    from datetime import UTC, datetime, timedelta

    return datetime.now(UTC) + timedelta(days=365 * years)


def main() -> None:
    if JAVA_HOME is None or not SMALI_JAR.exists():
        raise SystemExit("Нужны jdk4py (pip install jdk4py) и smali.jar")
    java = JAVA_HOME / "bin" / "java"

    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True, exist_ok=True)

    # 1. Web-ассеты (JPEG)
    build_web_assets(WORK)

    # 2. dex
    smali_file = WORK / "MainActivity.smali"
    smali_file.write_text(MAIN_SMALI, encoding="utf-8")
    run([java, "-jar", SMALI_JAR, smali_file, "-o", WORK / "classes.dex"])
    print("classes.dex:", (WORK / "classes.dex").stat().st_size, "байт")

    # 3. Манифест — НАСТОЯЩИЙ, сгенерированный aapt2 (resource ID верные).
    #    Ручной генератор давал сдвинутые ID атрибутов -> Android отклонял пакет.
    manifest = (ROOT / "novel_app" / "AndroidManifest.bin").read_bytes()
    (WORK / "AndroidManifest.xml").write_bytes(manifest)
    arsc = ROOT / "novel_app" / "resources.arsc"
    if arsc.exists():
        (WORK / "resources.arsc").write_bytes(arsc.read_bytes())
        print("resources.arsc:", arsc.stat().st_size, "байт")
    res_src = ROOT / "novel_app" / "res"
    if res_src.exists():
        shutil.copytree(res_src, WORK / "res")
        print("res/: иконки скопированы")
    print("AndroidManifest.xml:", len(manifest), "байт")
    # самопроверка: парсим наш же манифест
    try:
        from pyaxmlparser import AXMLPrinter  # type: ignore

        xml = AXMLPrinter(manifest).get_xml()
        assert "com.lilith.novel" in xml and "MainActivity" in xml
        print("Манифест прочитан парсером OK")
    except Exception as exc:  # noqa: BLE001
        print("⚠️ pyaxmlparser не смог прочитать манифест:", exc)

    # 4. zip-сборка APK
    if OUT.exists():
        OUT.unlink()
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_STORED) as z:
        z.write(WORK / "AndroidManifest.xml", "AndroidManifest.xml")
        z.write(WORK / "classes.dex", "classes.dex")
        arsc = WORK / "resources.arsc"
        if arsc.exists():
            z.write(arsc, "resources.arsc")
        res_dir = WORK / "res"
        if res_dir.exists():
            for f in sorted(res_dir.rglob("*")):
                if f.is_file():
                    z.write(f, "res/" + f.relative_to(res_dir).as_posix())
        for f in sorted((WORK / "novel").rglob("*")):
            if f.is_file():
                z.write(f, "assets/novel/" + f.relative_to(WORK / "novel").as_posix())

    # 5. Подпись: схема v1 (JAR) с ИСПРАВЛЕННЫМИ диджестами секций.
    #    (v2-блок не добавляем: targetSdk 28, Android принимает v1.)
    sign_v1(OUT)

    size_mb = OUT.stat().st_size / 1024 / 1024
    print(f"\n✅ APK собран и подписан: {OUT} ({size_mb:.1f} МБ)")


if __name__ == "__main__":
    main()
