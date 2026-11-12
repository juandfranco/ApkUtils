"""
Claves de firma: de dónde salen, su huella (SHA-256) y cómo exportarlas.

Android solo deja actualizar una app si el APK nuevo está firmado con la
MISMA clave que el instalado. Por eso la app deja elegir la clave de forma
explícita en vez de depender de qué encuentre el firmador en cada PC:

- "pc":       la clave debug de este PC (%USERPROFILE%\\.android\\debug.keystore),
              que Android Studio genera al azar en cada equipo.
- "embedded": la clave debug que lleva dentro uber-apk-signer. Es la MISMA en
              todos los PCs (la que se usa cuando un PC no tiene debug.keystore).
- "custom":   un keystore propio (.jks / .keystore / .p12) del usuario.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import struct
import subprocess
import zipfile
from dataclasses import dataclass
from datetime import datetime

from . import apk_tools

DEBUG_ALIAS = "androiddebugkey"
DEBUG_PASSWORD = "android"

SOURCE_PC = "pc"
SOURCE_EMBEDDED = "embedded"
SOURCE_CUSTOM = "custom"

SOURCE_LABELS = {
    SOURCE_PC: "Clave debug de este PC",
    SOURCE_EMBEDDED: "Clave del firmador (igual en todos los PCs)",
    SOURCE_CUSTOM: "Keystore propio",
}


@dataclass
class SigningKey:
    source: str
    keystore: str
    alias: str
    store_pass: str
    key_pass: str

    @property
    def label(self) -> str:
        return SOURCE_LABELS.get(self.source, self.source)

    def signer_args(self) -> list[str]:
        return [
            "--ks", self.keystore,
            "--ksAlias", self.alias,
            "--ksPass", self.store_pass,
            "--ksKeyPass", self.key_pass or self.store_pass,
        ]

    def secrets(self) -> list[str]:
        return [p for p in (self.store_pass, self.key_pass) if p]


# ------------------------------------------------------------- fuentes ---
def pc_debug_keystore() -> str:
    return os.path.join(os.path.expanduser("~"), ".android", "debug.keystore")


def embedded_keystore() -> str:
    """Extrae (una vez) la clave debug que trae uber-apk-signer y devuelve su ruta."""
    dest = os.path.join(apk_tools.tools_dir(), "uber-apk-signer-debug.keystore")
    if not os.path.isfile(dest):
        jar = apk_tools.signer_path()
        if not os.path.isfile(jar):
            raise RuntimeError("Falta el firmador: pulsa 'Descargar Java + herramientas'.")
        with zipfile.ZipFile(jar) as zf:
            data = zf.read("debug.keystore")
        with open(dest + ".part", "wb") as f:
            f.write(data)
        os.replace(dest + ".part", dest)
    return dest


def default_source() -> str:
    """La que usaba la app antes de existir el selector."""
    return SOURCE_PC if os.path.isfile(pc_debug_keystore()) else SOURCE_EMBEDDED


def resolve_key(
    source: str,
    custom_path: str = "",
    custom_alias: str = "",
    custom_store_pass: str = "",
    custom_key_pass: str = "",
) -> SigningKey:
    if source == SOURCE_PC:
        path = pc_debug_keystore()
        if not os.path.isfile(path):
            raise RuntimeError(f"Este PC no tiene clave debug ({path}).")
        return SigningKey(source, path, DEBUG_ALIAS, DEBUG_PASSWORD, DEBUG_PASSWORD)
    if source == SOURCE_EMBEDDED:
        return SigningKey(
            source, embedded_keystore(), DEBUG_ALIAS, DEBUG_PASSWORD, DEBUG_PASSWORD
        )
    if source == SOURCE_CUSTOM:
        if not custom_path or not os.path.isfile(custom_path):
            raise RuntimeError("Selecciona un archivo de keystore válido.")
        if not custom_store_pass:
            raise RuntimeError("Indica la contraseña del keystore.")
        key = SigningKey(
            source, custom_path, custom_alias.strip(), custom_store_pass,
            custom_key_pass or custom_store_pass,
        )
        if not key.alias:
            key.alias = keystore_info(key).alias
        return key
    raise ValueError(f"Fuente de clave desconocida: {source}")


# ------------------------------------------------------- huella (keytool) ---
@dataclass
class KeystoreInfo:
    alias: str
    sha256: str
    owner: str


_java_home_cache: str | None = None


def _keytool() -> str:
    """keytool del mismo Java que usa la app (está en cualquier JRE)."""
    global _java_home_cache
    exe = "keytool.exe" if os.name == "nt" else "keytool"
    java = apk_tools.find_java()
    if not java:
        raise RuntimeError("Java no disponible.")
    candidate = os.path.join(os.path.dirname(os.path.realpath(java)), exe)
    if os.path.isfile(candidate):
        return candidate
    # java.exe puede ser un acceso directo (p. ej. Oracle javapath): pedimos java.home.
    if _java_home_cache is None:
        out = subprocess.run(
            [java, "-XshowSettings:properties", "-version"],
            capture_output=True, text=True, errors="replace",
            creationflags=apk_tools._NO_WINDOW,
        )
        m = re.search(r"java\.home = (.+)", out.stderr + out.stdout)
        _java_home_cache = m.group(1).strip() if m else ""
    candidate = os.path.join(_java_home_cache, "bin", exe)
    if os.path.isfile(candidate):
        return candidate
    raise RuntimeError("No se encontró keytool junto a Java.")


def keystore_info(key: SigningKey) -> KeystoreInfo:
    """Alias, huella SHA-256 y titular de la clave (usa keytool)."""
    cmd = [
        _keytool(), "-J-Duser.language=en", "-J-Duser.country=US",
        "-list", "-v", "-keystore", key.keystore, "-storepass", key.store_pass,
    ]
    if key.alias:
        cmd += ["-alias", key.alias]
    out = subprocess.run(
        cmd, capture_output=True, text=True, errors="replace",
        creationflags=apk_tools._NO_WINDOW,
    )
    text = out.stdout + out.stderr
    if out.returncode != 0:
        if "password was incorrect" in text or "Keystore was tampered" in text:
            raise RuntimeError("La contraseña del keystore no es correcta.")
        if "does not exist" in text and key.alias:
            raise RuntimeError(f"El keystore no tiene el alias '{key.alias}'.")
        m = re.search(r"keytool error: (.+)", text)
        msg = m.group(1).strip() if m else "error desconocido"
        raise RuntimeError(f"No se pudo leer el keystore: {msg}")
    # Primera entrada con clave privada.
    for block in re.split(r"\n(?=Alias name:)", text):
        alias = re.search(r"Alias name:\s*(.+)", block)
        sha = re.search(r"SHA256:\s*([0-9A-F:]{95})", block)
        if alias and sha and "PrivateKeyEntry" in block:
            owner = re.search(r"Owner:\s*(.+)", block)
            return KeystoreInfo(
                alias.group(1).strip(), sha.group(1),
                owner.group(1).strip() if owner else "",
            )
    raise RuntimeError("El keystore no contiene ninguna clave privada.")


# --------------------------------------------- huella del APK (sin Java) ---
_V2_ID = 0x7109871A
_V3_ID = 0xF05368C0


def apk_signer_sha256(apk_path: str) -> str | None:
    """Huella SHA-256 del certificado que firmó el APK (v3, v2 o v1)."""
    with open(apk_path, "rb") as f:
        data = f.read()
    der = _cert_from_signing_block(data) or _cert_from_v1(apk_path)
    if not der:
        return None
    return format_fingerprint(hashlib.sha256(der).hexdigest())


def format_fingerprint(hexdigest: str) -> str:
    h = hexdigest.upper()
    return ":".join(h[i:i + 2] for i in range(0, len(h), 2))


def _lp(buf: bytes, off: int) -> tuple[bytes, int]:
    (n,) = struct.unpack_from("<I", buf, off)
    return buf[off + 4: off + 4 + n], off + 4 + n


def _cert_from_signing_block(data: bytes) -> bytes | None:
    eocd = data.rfind(b"PK\x05\x06", max(0, len(data) - 65557))
    if eocd < 0:
        return None
    (cd_offset,) = struct.unpack_from("<I", data, eocd + 16)
    if cd_offset < 24 or data[cd_offset - 16: cd_offset] != b"APK Sig Block 42":
        return None
    (size,) = struct.unpack_from("<Q", data, cd_offset - 24)
    # Bloque: [size u64][pares id-valor ...][size u64]["APK Sig Block 42"]
    pos, end = cd_offset - size, cd_offset - 24
    blocks: dict[int, bytes] = {}
    while pos + 12 <= end:
        (length,) = struct.unpack_from("<Q", data, pos)
        (pid,) = struct.unpack_from("<I", data, pos + 8)
        blocks[pid] = data[pos + 12: pos + 8 + length]
        pos += 8 + length
    for pid in (_V3_ID, _V2_ID):
        if pid not in blocks:
            continue
        try:
            signers, _ = _lp(blocks[pid], 0)
            signer, _ = _lp(signers, 0)
            signed_data, _ = _lp(signer, 0)
            _digests, off = _lp(signed_data, 0)
            certs, _ = _lp(signed_data, off)
            cert, _ = _lp(certs, 0)
            return cert
        except struct.error:
            continue
    return None


def _der(buf: bytes, off: int) -> tuple[int, int, int]:
    """(tag, inicio_contenido, fin) del elemento DER en `off`."""
    tag = buf[off]
    n = buf[off + 1]
    off += 2
    if n & 0x80:
        k = n & 0x7F
        n = int.from_bytes(buf[off: off + k], "big")
        off += k
    return tag, off, off + n


def _cert_from_v1(apk_path: str) -> bytes | None:
    try:
        with zipfile.ZipFile(apk_path) as zf:
            names = [
                n for n in zf.namelist()
                if re.fullmatch(r"META-INF/[^/]+\.(RSA|DSA|EC)", n, re.I)
            ]
            if not names:
                return None
            p7 = zf.read(names[0])
        # ContentInfo { oid, [0] { SignedData { ver, algs, content, [0] certs } } }
        _, c, _ = _der(p7, 0)
        _, c, _ = _der(p7, _der(p7, c)[2])      # [0] explícito
        _, c, end = _der(p7, c)                 # SignedData
        for _ in range(3):                      # version, digestAlgs, contentInfo
            c = _der(p7, c)[2]
        tag, c, _ = _der(p7, c)
        if tag != 0xA0:
            return None
        _, _, cert_end = _der(p7, c)
        return p7[c:cert_end]
    except (zipfile.BadZipFile, IndexError, KeyError):
        return None


def identify(sha256: str | None) -> str:
    """Nombre legible de una huella si coincide con una clave conocida."""
    if not sha256:
        return "sin firma"
    for source in (SOURCE_PC, SOURCE_EMBEDDED):
        try:
            if keystore_info(resolve_key(source)).sha256 == sha256:
                return SOURCE_LABELS[source]
        except Exception:
            continue
    return "otra clave (desconocida en este PC)"


# ------------------------------------------------------------ exportar ---
def export_key(key: SigningKey, dest_dir: str) -> str:
    """Copia el keystore a `dest_dir` junto a un LEEME.txt. Devuelve la ruta."""
    info = keystore_info(key)
    os.makedirs(dest_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    base = {
        SOURCE_PC: "debug-este-pc",
        SOURCE_EMBEDDED: "debug-uber-apk-signer",
    }.get(key.source, os.path.splitext(os.path.basename(key.keystore))[0])
    ext = os.path.splitext(key.keystore)[1] or ".keystore"
    dest = os.path.join(dest_dir, f"{base}_{stamp}{ext}")
    shutil.copyfile(key.keystore, dest)

    lines = [
        f"Clave de firma exportada por APK Renamer ({datetime.now():%Y-%m-%d %H:%M})",
        "",
        f"Tipo:      {key.label}",
        f"Origen:    {key.keystore}",
        f"Archivo:   {os.path.basename(dest)}",
        f"Alias:     {info.alias}",
        f"Titular:   {info.owner}",
        f"SHA-256:   {info.sha256}",
    ]
    if key.source in (SOURCE_PC, SOURCE_EMBEDDED):
        lines += [
            f"Contraseña keystore / clave: {DEBUG_PASSWORD}",
            "",
            "Para usarla en otro PC como su clave debug, cópiala como:",
            r"  %USERPROFILE%\.android\debug.keystore",
        ]
    else:
        lines += ["", "Las contraseñas NO se guardan aquí: apúntalas en un lugar seguro."]
    with open(dest + ".LEEME.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return dest
