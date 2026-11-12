"""
Permisos del APK: leerlos del AndroidManifest, clasificarlos y quitarlos.

Quitar un permiso = borrar su <uses-permission> (o <uses-permission-sdk-23>)
del manifest. El código de la app no cambia, así que:

- Permisos PELIGROSOS (cámara, ubicación, contactos...): el usuario ya puede
  negarlos desde Android 6, por lo que las apps suelen tolerar no tenerlos.
- Permisos que la app da por hechos (INTERNET, servicios en primer plano...):
  quitarlos puede hacer que la app se cierre al intentar usarlos.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

from . import renamer

_AND = renamer._AND
_TAGS = ("uses-permission", "uses-permission-sdk-23")

KIND_DANGEROUS = "peligroso"
KIND_SPECIAL = "especial"
KIND_NORMAL = "normal"

# Permisos de tiempo de ejecución ("dangerous") de Android.
_DANGEROUS = {
    "READ_CALENDAR", "WRITE_CALENDAR", "CAMERA", "READ_CONTACTS", "WRITE_CONTACTS",
    "GET_ACCOUNTS", "ACCESS_FINE_LOCATION", "ACCESS_COARSE_LOCATION",
    "ACCESS_BACKGROUND_LOCATION", "RECORD_AUDIO", "READ_PHONE_STATE",
    "READ_PHONE_NUMBERS", "CALL_PHONE", "ANSWER_PHONE_CALLS", "READ_CALL_LOG",
    "WRITE_CALL_LOG", "ADD_VOICEMAIL", "USE_SIP", "PROCESS_OUTGOING_CALLS",
    "BODY_SENSORS", "BODY_SENSORS_BACKGROUND", "ACTIVITY_RECOGNITION", "SEND_SMS",
    "RECEIVE_SMS", "READ_SMS", "RECEIVE_WAP_PUSH", "RECEIVE_MMS",
    "READ_EXTERNAL_STORAGE", "WRITE_EXTERNAL_STORAGE", "ACCESS_MEDIA_LOCATION",
    "READ_MEDIA_IMAGES", "READ_MEDIA_VIDEO", "READ_MEDIA_AUDIO",
    "READ_MEDIA_VISUAL_USER_SELECTED", "POST_NOTIFICATIONS", "NEARBY_WIFI_DEVICES",
    "BLUETOOTH_SCAN", "BLUETOOTH_CONNECT", "BLUETOOTH_ADVERTISE", "UWB_RANGING",
    "ACCEPT_HANDOVER",
}

# Permisos "especiales": muy sensibles, se conceden desde Ajustes.
_SPECIAL = {
    "SYSTEM_ALERT_WINDOW", "REQUEST_INSTALL_PACKAGES", "QUERY_ALL_PACKAGES",
    "MANAGE_EXTERNAL_STORAGE", "WRITE_SETTINGS", "PACKAGE_USAGE_STATS",
    "SCHEDULE_EXACT_ALARM", "USE_EXACT_ALARM", "REQUEST_IGNORE_BATTERY_OPTIMIZATIONS",
    "REQUEST_DELETE_PACKAGES", "READ_LOGS", "MANAGE_OWN_CALLS",
    "BIND_NOTIFICATION_LISTENER_SERVICE", "ACCESS_NOTIFICATION_POLICY",
}

# Normalmente imprescindibles: quitarlos suele romper la app.
_NEEDED = {
    "INTERNET", "ACCESS_NETWORK_STATE", "ACCESS_WIFI_STATE", "WAKE_LOCK",
    "FOREGROUND_SERVICE",
}


@dataclass(frozen=True)
class Permission:
    name: str

    @property
    def short(self) -> str:
        return self.name.removeprefix("android.permission.")

    @property
    def is_android(self) -> bool:
        return self.name.startswith("android.permission.")

    @property
    def kind(self) -> str:
        if not self.is_android:
            return KIND_NORMAL
        if self.short in _DANGEROUS:
            return KIND_DANGEROUS
        if self.short in _SPECIAL:
            return KIND_SPECIAL
        return KIND_NORMAL

    @property
    def risky_to_remove(self) -> bool:
        s = self.short
        return self.is_android and (s in _NEEDED or s.startswith("FOREGROUND_SERVICE"))


def _load(decoded_dir: str) -> tuple[ET.Element, str]:
    path = renamer._manifest_path(decoded_dir)
    text = open(path, encoding="utf-8").read()
    renamer._register_namespaces(text)
    return ET.fromstring(text), path


def read_permissions(decoded_dir: str) -> list[Permission]:
    """Permisos pedidos por el APK, sin repetidos y en orden de aparición."""
    root, _ = _load(decoded_dir)
    seen: dict[str, None] = {}
    for el in root:
        if el.tag in _TAGS and el.get(f"{_AND}name"):
            seen.setdefault(el.get(f"{_AND}name"), None)
    return [Permission(n) for n in seen]


def remove_permissions(decoded_dir: str, names: list[str] | set[str]) -> list[str]:
    """Quita esos permisos del manifest. Devuelve los que se quitaron."""
    wanted = set(names)
    if not wanted:
        return []
    root, path = _load(decoded_dir)
    removed: list[str] = []
    for el in list(root):
        name = el.get(f"{_AND}name")
        if el.tag in _TAGS and name in wanted:
            root.remove(el)
            if name not in removed:
                removed.append(name)
    if removed:
        renamer._write_manifest(root, path)
    return removed
