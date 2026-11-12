"""
Ajustes que se recuerdan entre ejecuciones.

Se guardan en %LOCALAPPDATA%\\ApkRenamer\\settings.json:

- "general": última clave de firma elegida, keystore propio, carpetas usadas.
- "apps":    un perfil por package ORIGINAL (p. ej. com.android.mgstv) con el
             nombre y package nuevos, la clave usada y la carpeta de salida,
             para que la próxima versión de esa app se procese con un clic.

La contraseña del keystore solo se guarda si el usuario lo pide, y cifrada con
DPAPI de Windows (solo la puede descifrar el mismo usuario en el mismo PC).
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

from . import apk_tools


def settings_path() -> str:
    return os.path.join(os.path.dirname(apk_tools.tools_dir()), "settings.json")


def load() -> dict[str, Any]:
    try:
        with open(settings_path(), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data.setdefault("general", {})
            data.setdefault("apps", {})
            return data
    except (OSError, ValueError):
        pass
    return {"general": {}, "apps": {}}


def save(data: dict[str, Any]) -> None:
    path = settings_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ------------------------------------------------ contraseña cifrada ---
def can_encrypt() -> bool:
    return os.name == "nt"


def encrypt(secret: str) -> str | None:
    """Cifra con DPAPI (Windows). Devuelve None si no es posible."""
    if not secret or not can_encrypt():
        return None
    try:
        return base64.b64encode(_dpapi(secret.encode("utf-8"), protect=True)).decode()
    except OSError:
        return None


def decrypt(token: str | None) -> str:
    if not token or not can_encrypt():
        return ""
    try:
        return _dpapi(base64.b64decode(token), protect=False).decode("utf-8")
    except (OSError, ValueError):
        return ""


def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    # Sin descripción ni entropía extra; 0x1 = CRYPTPROTECT_UI_FORBIDDEN.
    ok = fn(ctypes.byref(blob_in), None, None, None, None, 0x1, ctypes.byref(blob_out))
    if not ok:
        raise OSError("DPAPI falló")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)
