"""
Orquesta el proceso completo: decodificar -> editar -> reconstruir -> firmar.
"""

from __future__ import annotations

import glob
import os
import shutil
import tempfile

from . import apk_tools, renamer


def load_apk_info(apk_path: str, log=print) -> tuple[str, str]:
    """Decodifica el APK en una carpeta temporal y devuelve (package, nombre)."""
    apk_tools.ensure_tools(log)
    work = tempfile.mkdtemp(prefix="apkinfo_")
    decoded = os.path.join(work, "app")
    try:
        log("Leyendo el APK ...")
        apk_tools.run_java_jar(
            apk_tools.apktool_path(),
            ["d", "-f", "-s", "-o", decoded, apk_path],
            log,
        )
        return renamer.read_info(decoded)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def process(
    apk_path: str,
    output_path: str,
    new_name: str | None,
    new_package: str | None,
    log=print,
) -> str:
    """Aplica los cambios y devuelve la ruta del APK final firmado."""
    apk_tools.ensure_tools(log)
    work = tempfile.mkdtemp(prefix="apkwork_")
    decoded = os.path.join(work, "app")
    try:
        # 1) Decodificar (-s mantiene el código compilado, más rápido y seguro).
        log("== Decodificando APK ==")
        apk_tools.run_java_jar(
            apk_tools.apktool_path(),
            ["d", "-f", "-s", "-o", decoded, apk_path],
            log,
        )

        # 2) Editar manifest / recursos.
        if new_name:
            log(f"== Cambiando nombre visible a: {new_name} ==")
            renamer.set_app_name(decoded, new_name)
        if new_package:
            log(f"== Cambiando package name a: {new_package} ==")
            old = renamer.set_package_name(decoded, new_package)
            log(f"   (package anterior: {old})")

        # 3) Reconstruir.
        log("== Reconstruyendo APK ==")
        unsigned = os.path.join(work, "unsigned.apk")
        apk_tools.run_java_jar(
            apk_tools.apktool_path(),
            ["b", "-o", unsigned, decoded],
            log,
        )

        # 4) Firmar (uber-apk-signer alinea y firma con una clave debug).
        log("== Firmando APK ==")
        out_dir = os.path.join(work, "signed")
        os.makedirs(out_dir, exist_ok=True)
        apk_tools.run_java_jar(
            apk_tools.signer_path(),
            ["--apks", unsigned, "--out", out_dir, "--overwrite", "--allowResign"],
            log,
        )

        produced = _find_signed(out_dir)
        if not produced:
            raise RuntimeError("No se encontró el APK firmado de salida.")

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        shutil.copyfile(produced, output_path)
        log(f"== Listo: {output_path} ==")
        return output_path
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _find_signed(out_dir: str) -> str | None:
    candidates = glob.glob(os.path.join(out_dir, "*.apk"))
    if not candidates:
        return None
    # Preferimos el que indique que está firmado.
    for c in candidates:
        if "Signed" in os.path.basename(c) or "signed" in os.path.basename(c):
            return c
    return candidates[0]
