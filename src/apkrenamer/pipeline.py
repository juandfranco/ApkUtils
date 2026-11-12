"""
Orquesta el proceso completo: decodificar -> editar -> reconstruir -> firmar.
"""

from __future__ import annotations

import glob
import os
import shutil
import tempfile
from typing import NamedTuple

from . import apk_tools, permissions, renamer, signing


class ApkInfo(NamedTuple):
    package: str
    name: str
    version_code: str
    version_name: str
    signer_sha256: str | None
    permissions: list[permissions.Permission] = []


def load_apk_info(apk_path: str, log=print) -> ApkInfo:
    """Decodifica el APK en una carpeta temporal y devuelve sus datos actuales."""
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
        package, name = renamer.read_info(decoded)
        code, vname = renamer.read_version(decoded)
        return ApkInfo(
            package, name, code, vname,
            signing.apk_signer_sha256(apk_path),
            permissions.read_permissions(decoded),
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)


def process(
    apk_path: str,
    output_path: str,
    new_name: str | None,
    new_package: str | None,
    log=print,
    new_version_code: str | None = None,
    new_version_name: str | None = None,
    key: signing.SigningKey | None = None,
    remove_permissions: list[str] | None = None,
) -> str:
    """Aplica los cambios y devuelve la ruta del APK final firmado."""
    apk_tools.ensure_tools(log)
    if key is None:
        key = signing.resolve_key(signing.default_source())
    key_info = signing.keystore_info(key)
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
            old = renamer.set_package_name(decoded, new_package, log)
            log(f"   (package anterior: {old})")
            if remove_permissions:
                # Los permisos propios `old.*` acaban de renombrarse a `new.*`.
                remove_permissions = [
                    renamer._swap_prefix(p, old, new_package) for p in remove_permissions
                ]
        if new_version_code is not None or new_version_name is not None:
            old_code, old_name = renamer.read_version(decoded)
            renamer.set_version(decoded, new_version_code, new_version_name)
            if new_version_code is not None:
                log(f"== Cambiando versionCode: {old_code or '?'} -> {new_version_code} ==")
            if new_version_name is not None:
                log(f"== Cambiando versionName: {old_name or '?'} -> {new_version_name} ==")
        if remove_permissions:
            removed = permissions.remove_permissions(decoded, remove_permissions)
            log(f"== Quitando {len(removed)} permiso(s) ==")
            for p in removed:
                log(f"   - {p}")
            missing = sorted(set(remove_permissions) - set(removed))
            if missing:
                log(f"   (no estaban en este APK: {', '.join(missing)})")

        # 3) Reconstruir.
        log("== Reconstruyendo APK ==")
        unsigned = os.path.join(work, "unsigned.apk")
        apk_tools.run_java_jar(
            apk_tools.apktool_path(),
            ["b", "-o", unsigned, decoded],
            log,
        )

        # 4) Firmar (uber-apk-signer alinea y firma con una clave debug).
        log(f"== Firmando APK con: {key.label} ==")
        log(f"   keystore: {key.keystore}")
        log(f"   alias: {key_info.alias}   SHA-256: {key_info.sha256}")
        out_dir = os.path.join(work, "signed")
        os.makedirs(out_dir, exist_ok=True)
        apk_tools.run_java_jar(
            apk_tools.signer_path(),
            ["--apks", unsigned, "--out", out_dir, "--allowResign", *key.signer_args()],
            log,
            secrets=key.secrets() if key.source == signing.SOURCE_CUSTOM else None,
        )

        produced = _find_signed(out_dir)
        if not produced:
            raise RuntimeError("No se encontró el APK firmado de salida.")

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        shutil.copyfile(produced, output_path)

        original = signing.apk_signer_sha256(apk_path)
        final = signing.apk_signer_sha256(output_path)
        if final != key_info.sha256:
            raise RuntimeError(
                f"El APK salió firmado con otra clave ({final}); se esperaba {key_info.sha256}."
            )
        if original and original != final:
            log("AVISO: la firma es distinta a la del APK original. Para instalarlo")
            log("   habrá que desinstalar antes la app original (o cambiar el package).")
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
