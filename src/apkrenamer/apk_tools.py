"""
Gestión de las herramientas externas (Java, apktool y firmador).

Mantiene todo en una carpeta de usuario escribible y descarga los .jar
necesarios la primera vez que se usan, para que la app sea "bajar y ejecutar".
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass

# Versiones de las herramientas que se descargan automáticamente.
APKTOOL_VERSION = "2.9.3"
APKTOOL_URL = (
    "https://github.com/iBotPeaches/Apktool/releases/download/"
    f"v{APKTOOL_VERSION}/apktool_{APKTOOL_VERSION}.jar"
)

SIGNER_VERSION = "1.3.0"
SIGNER_URL = (
    "https://github.com/patrickfav/uber-apk-signer/releases/download/"
    f"v{SIGNER_VERSION}/uber-apk-signer-{SIGNER_VERSION}.jar"
)

# En Windows evitamos que aparezcan ventanas de consola al lanzar procesos.
_NO_WINDOW = 0
if os.name == "nt":
    _NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def tools_dir() -> str:
    """Carpeta escribible donde guardamos los .jar descargados."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "ApkRenamer", "tools")
    os.makedirs(path, exist_ok=True)
    return path


def apktool_path() -> str:
    return os.path.join(tools_dir(), f"apktool_{APKTOOL_VERSION}.jar")


def signer_path() -> str:
    return os.path.join(tools_dir(), f"uber-apk-signer-{SIGNER_VERSION}.jar")


def find_java() -> str | None:
    """Devuelve la ruta al ejecutable de Java o None si no está instalado."""
    # 1) java en el PATH
    java = shutil.which("java")
    if java:
        return java
    # 2) JAVA_HOME
    home = os.environ.get("JAVA_HOME")
    if home:
        candidate = os.path.join(home, "bin", "java.exe" if os.name == "nt" else "java")
        if os.path.isfile(candidate):
            return candidate
    return None


@dataclass
class ToolStatus:
    java: str | None
    apktool: bool
    signer: bool

    @property
    def ready(self) -> bool:
        return bool(self.java) and self.apktool and self.signer


def check_tools() -> ToolStatus:
    return ToolStatus(
        java=find_java(),
        apktool=os.path.isfile(apktool_path()),
        signer=os.path.isfile(signer_path()),
    )


def _download(url: str, dest: str, log) -> None:
    log(f"Descargando {os.path.basename(dest)} ...")
    tmp = dest + ".part"
    with urllib.request.urlopen(url) as resp, open(tmp, "wb") as out:
        shutil.copyfileobj(resp, out)
    os.replace(tmp, dest)
    log(f"  -> guardado en {dest}")


def ensure_tools(log=print) -> None:
    """Descarga apktool y el firmador si faltan. Lanza si falta Java."""
    if not find_java():
        raise RuntimeError(
            "No se encontró Java. Instala Java 8 o superior (Adoptium Temurin) "
            "y vuelve a intentarlo: https://adoptium.net/"
        )
    if not os.path.isfile(apktool_path()):
        _download(APKTOOL_URL, apktool_path(), log)
    if not os.path.isfile(signer_path()):
        _download(SIGNER_URL, signer_path(), log)


def run_java_jar(jar: str, args: list[str], log=print) -> None:
    """Ejecuta `java -jar jar args...` retransmitiendo la salida al log."""
    java = find_java()
    if not java:
        raise RuntimeError("Java no disponible.")
    cmd = [java, "-jar", jar, *args]
    log("> " + " ".join(os.path.basename(c) if i < 3 else c for i, c in enumerate(cmd)))
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_NO_WINDOW,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        log(line.rstrip())
    code = proc.wait()
    if code != 0:
        raise RuntimeError(f"El proceso terminó con código {code}.")
