"""Правильная JAR/PKCS#7 (CMS) подпись — как у jarsigner.

Android libcore (PackageParser) при установке APK проверяет подпись v1 так:
1. SHA-256 диджесты файлов в MANIFEST.MF;
2. SHA-256 диджесты манифеста и секций в CERT.SF;
3. PKCS#7 SignedData в CERT.RSA:
   - signedAttrs (contentType, messageDigest, signingTime),
   - подпись RSA-PKCS1v15-SHA256 по DER(SignedAttributes).

cryptography не умеет строить CMS с signedAttrs в нужном виде, поэтому
строим SignedData вручную (полный контроль над DER).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


# ---------------------------------------------------------------------------
# DER-кодировщик (минимум, достаточный для CMS)
# ---------------------------------------------------------------------------

def der_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def tlv(tag: int, content: bytes) -> bytes:
    return bytes([tag]) + der_len(len(content)) + content


def seq(*parts: bytes) -> bytes:
    return tlv(0x30, b"".join(parts))


def sset(*parts: bytes) -> bytes:
    """SET OF: элементы сортируются по DER-байтам (требование DER)."""
    return tlv(0x31, b"".join(sorted(parts)))


def oid_bytes(oid: str) -> bytes:
    parts = [int(p) for p in oid.split(".")]
    out = bytearray([parts[0] * 40 + parts[1]])
    for p in parts[2:]:
        chunk = bytearray([p & 0x7F])
        p >>= 7
        while p:
            chunk.insert(0, 0x80 | (p & 0x7F))
            p >>= 7
        out += chunk
    return bytes(out)


def oid(oid: str) -> bytes:
    return tlv(0x06, oid_bytes(oid))


def integer(n: int) -> bytes:
    b = n.to_bytes(max(1, (n.bit_length() + 7) // 8), "big")
    if b[0] & 0x80:
        b = b"\x00" + b
    return tlv(0x02, b)


def octets(b: bytes) -> bytes:
    return tlv(0x04, b)


def null() -> bytes:
    return b"\x05\x00"


def utctime(dt: datetime) -> bytes:
    s = dt.strftime("%y%m%d%H%M%SZ").encode()
    return tlv(0x17, s)


# ---------------------------------------------------------------------------
# CMS SignedData (как sun.security.pkcs.PKCS7 / jarsigner)
# ---------------------------------------------------------------------------

ID_DATA = "1.2.840.113549.1.7.1"          # id-data
OID_SHA256 = "2.16.840.1.101.3.4.2.1"     # sha256
OID_RSA = "1.2.840.113549.1.1.1"          # rsaEncryption
OID_CONTENT_TYPE = "1.2.840.113549.1.9.3"
OID_MESSAGE_DIGEST = "1.2.840.113549.1.9.4"
OID_SIGNING_TIME = "1.2.840.113549.1.9.5"
OID_SIGNED_DATA = "1.2.840.113549.1.7.2"


def _attr(oid_str: str, value_der: bytes) -> bytes:
    """Attribute ::= SEQUENCE { attrType OID, attrValues SET OF ANY }"""
    return seq(oid(oid_str), sset(value_der))


def build_pkcs7_signed_data(cert: x509.Certificate, key, content: bytes) -> bytes:
    """Строит ContentInfo { contentType=id-signedData, content [0] SignedData }."""
    # 1. digest и атрибуты
    digest = hashlib.sha256(content).digest()
    now = datetime.now(UTC).replace(microsecond=0)
    signed_attrs = sset(
        _attr(OID_CONTENT_TYPE, oid(ID_DATA)),
        _attr(OID_MESSAGE_DIGEST, octets(digest)),
        _attr(OID_SIGNING_TIME, utctime(now)),
    )
    # SignedAttributes — это [0] IMPLICIT SET
    signed_attrs_der = tlv(0xA0, signed_attrs)

    # 2. Подпись по DER(SignedAttributes)
    signature = key.sign(signed_attrs_der, padding.PKCS1v15(), hashes.SHA256())

    # 3. Сертификат и issuerAndSerialNumber
    cert_der = cert.public_bytes(serialization.Encoding.DER)
    issuer_der, serial = _extract_issuer_serial(cert_der)
    sid = seq(issuer_der, integer(serial))

    # 4. SignerInfo
    signer_info = seq(
        integer(1),                                   # version
        sid,                                          # issuerAndSerialNumber
        seq(oid(OID_SHA256), null()),                 # digestAlgorithm
        signed_attrs_der,                             # signedAttrs [0]
        seq(oid(OID_RSA), null()),                    # signatureAlgorithm
        octets(signature),                            # signature
    )

    # 5. SignedData
    signed_data = seq(
        integer(1),                                   # version CMS
        sset(seq(oid(OID_SHA256), null())),           # digestAlgorithms
        seq(oid(ID_DATA)),                            # encapContentInfo (без content)
        tlv(0xA0, sset(cert_der)),                    # certificates [0] IMPLICIT SET
        sset(signer_info),                            # signerInfos
    )

    # 6. ContentInfo
    content_info = seq(oid(OID_SIGNED_DATA), tlv(0xA0, signed_data))
    return content_info


def _extract_issuer_serial(cert_der: bytes) -> tuple[bytes, int]:
    """Достаёт issuer (DER) и серийный номер из сертификата."""
    # Certificate ::= SEQUENCE { tbsCertificate, ... }
    pos = 0

    def read_tlv(data: bytes, p: int):
        tag = data[p]
        p += 1
        b = data[p]
        p += 1
        if b & 0x80:
            n = b & 0x7F
            length = int.from_bytes(data[p:p + n], "big")
            p += n
        else:
            length = b
        return tag, data[p:p + length], p + length

    _tag, tbs, _p = read_tlv(cert_der, pos)
    # tbsCertificate ::= SEQUENCE { [0] EXPLICIT version?, serialNumber, signature, issuer, ... }
    tpos = 0
    if tbs[tpos] == 0xA0:  # version [0] EXPLICIT
        _, _v, tpos = read_tlv(tbs, tpos)
    _t, serial_tlv, tpos = read_tlv(tbs, tpos)   # serialNumber INTEGER
    serial = int.from_bytes(serial_tlv, "big")
    _t, _sig, tpos = read_tlv(tbs, tpos)         # signature AlgorithmIdentifier
    _t, issuer, _p = read_tlv(tbs, tpos)         # issuer Name
    return issuer, serial
