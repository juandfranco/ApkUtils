"""
Gestión de las herramientas externas (Java, apktool y firmador).

Todo se guarda en una carpeta de usuario escribible y se descarga la primera
vez que se usa, incluido un Java (JRE) portátil. Así la app es 100% "bajar y
ejecutar": no hay que instalar nada manualmente.
"""

from __future__ import annotations

import glob
import os
import platform
import shutil
import ssl
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
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

# Java (JRE) portátil de Adoptium Temurin. Se descarga desde GitHub Releases
# (host fiable) si no hay Java en el PC.
JRE_TAG = "jdk-17.0.13%2B11"
JRE_BUILD = "17.0.13_11"
JRE_BASE = (
    "https://github.com/adoptium/temurin17-binaries/releases/download/"
    f"{JRE_TAG}/"
)

# En Windows evitamos que aparezcan ventanas de consola al lanzar procesos.
_NO_WINDOW = 0
if os.name == "nt":
    _NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

# Cache de la ruta a un Java portátil ya extraído.
_bundled_java_cache: str | None = None


def tools_dir() -> str:
    """Carpeta escribible donde guardamos lo descargado."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "ApkRenamer", "tools")
    os.makedirs(path, exist_ok=True)
    return path


def apktool_path() -> str:
    return os.path.join(tools_dir(), f"apktool_{APKTOOL_VERSION}.jar")


def signer_path() -> str:
    return os.path.join(tools_dir(), f"uber-apk-signer-{SIGNER_VERSION}.jar")


def _jre_dir() -> str:
    return os.path.join(tools_dir(), "jre")


def _java_exe_name() -> str:
    return "java.exe" if os.name == "nt" else "java"


def _bundled_java() -> str | None:
    """Busca un java.exe dentro del JRE portátil ya extraído."""
    global _bundled_java_cache
    if _bundled_java_cache and os.path.isfile(_bundled_java_cache):
        return _bundled_java_cache
    pattern = os.path.join(_jre_dir(), "**", "bin", _java_exe_name())
    for found in glob.glob(pattern, recursive=True):
        if os.path.isfile(found):
            _bundled_java_cache = found
            return found
    return None


def find_java() -> str | None:
    """Java del sistema (PATH o JAVA_HOME) o el JRE portátil descargado."""
    java = shutil.which("java")
    if java:
        return java
    home = os.environ.get("JAVA_HOME")
    if home:
        candidate = os.path.join(home, "bin", _java_exe_name())
        if os.path.isfile(candidate):
            return candidate
    return _bundled_java()


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


def _ssl_context() -> ssl.SSLContext:
    """Contexto SSL robusto: usa certifi y/o los certificados del sistema."""
    ctx = ssl.create_default_context()
    try:
        import certifi  # incluido en el .exe; valida HTTPS sin depender del SO

        ctx.load_verify_locations(certifi.where())
    except Exception:
        pass
    try:
        ctx.load_default_certs()  # añade los certificados del sistema (Windows)
    except Exception:
        pass
    return ctx


def _open_url(url: str):
    # GitHub/Adoptium rechazan el User-Agent por defecto de urllib (403).
    req = urllib.request.Request(url, headers={"User-Agent": "ApkRenamer"})
    try:
        return urllib.request.urlopen(req, context=_ssl_context())
    except ssl.SSLError:
        # Último recurso: descargar sin verificar el certificado. Las URLs son
        # fijas y de confianza (GitHub Releases), así que es aceptable aquí.
        insecure = ssl.create_default_context()
        insecure.check_hostname = False
        insecure.verify_mode = ssl.CERT_NONE
        return urllib.request.urlopen(req, context=insecure)


def _download(url: str, dest: str, log) -> None:
    log(f"Descargando {os.path.basename(dest)} ...")
    tmp = dest + ".part"
    with _open_url(url) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        next_mark = 10
        with open(tmp, "wb") as out:
            while True:
                chunk = resp.read(262144)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if total:
                    pct = done * 100 // total
                    if pct >= next_mark:
                        log(f"   {pct}%  ({done // 1048576} MB)")
                        next_mark = pct - (pct % 10) + 10
    os.replace(tmp, dest)
    log(f"   -> guardado en {dest}")


def _jre_download_url() -> tuple[str, bool]:
    """(url, es_zip) del JRE portátil según SO y arquitectura."""
    if os.name == "nt":
        os_name, ext, is_zip = "windows", "zip", True
    elif sys.platform == "darwin":
        os_name, ext, is_zip = "mac", "tar.gz", False
    else:
        os_name, ext, is_zip = "linux", "tar.gz", False

    machine = platform.machine().lower()
    if machine in ("aarch64", "arm64") and os_name != "windows":
        arch = "aarch64"
    else:
        arch = "x64"

    filename = f"OpenJDK17U-jre_{arch}_{os_name}_hotspot_{JRE_BUILD}.{ext}"
    return JRE_BASE + filename, is_zip


def ensure_java(log=print) -> str:
    """Devuelve una ruta a Java; descarga un JRE portátil si hace falta."""
    java = find_java()
    if java:
        return java

    log("No se encontró Java en el sistema. Descargando un Java portátil...")
    os.makedirs(_jre_dir(), exist_ok=True)
    url, is_zip = _jre_download_url()
    archive = os.path.join(_jre_dir(), "jre.zip" if is_zip else "jre.tar.gz")
    _download(url, archive, log)

    log("Extrayendo Java...")
    if is_zip:
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(_jre_dir())
    else:
        with tarfile.open(archive) as tf:
            tf.extractall(_jre_dir())
    try:
        os.remove(archive)
    except OSError:
        pass

    global _bundled_java_cache
    _bundled_java_cache = None
    java = _bundled_java()
    if not java:
        raise RuntimeError("No se pudo preparar el Java portátil descargado.")
    if os.name != "nt":
        try:
            os.chmod(java, 0o755)
        except OSError:
            pass
    log(f"   Java listo: {java}")
    return java


def ensure_tools(log=print) -> None:
    """Garantiza que Java, apktool y el firmador están disponibles."""
    ensure_java(log)
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
