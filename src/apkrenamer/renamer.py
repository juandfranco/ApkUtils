"""
Lógica para cambiar el nombre visible y el package name (application ID)
de un APK usando apktool + uber-apk-signer.

Estrategia para el cambio de package name
------------------------------------------
Se cambia únicamente el atributo `package` del AndroidManifest (el
application ID que usa Android para identificar/instalar la app). Antes de
cambiarlo se "expanden" los nombres de componentes relativos (por ejemplo
`.MainActivity`) a su nombre completo con el package ANTIGUO, de modo que
sigan apuntando a las clases reales. Así se logra un renombrado fiable sin
tener que mover el código smali, que es lo que la mayoría de usuarios quiere
(rebrandear e instalar junto a la app original).

Para poder instalarse JUNTO a la original también hay que renombrar lo que
Android exige que sea único en el dispositivo y que suele llevar el package:

- las `android:authorities` de los <provider> (si no: INSTALL_FAILED_CONFLICTING_PROVIDER);
- los permisos propios <permission> y sus referencias
  (si no: INSTALL_FAILED_DUPLICATE_PERMISSION).

Solo se cambia el prefijo `paquete.viejo.` -> `paquete.nuevo.`. Las librerías
(androidx, Firebase, FileProvider...) construyen esos nombres con
getPackageName() en tiempo de ejecución, así que el renombrado coincide con lo
que la app espera.
"""

from __future__ import annotations

import glob
import html
import os
import re
import xml.etree.ElementTree as ET

ANDROID_NS = "http://schemas.android.com/apk/res/android"
_AND = f"{{{ANDROID_NS}}}"

# Etiquetas del manifest cuyo android:name apunta a una clase de código.
_COMPONENT_TAGS = {
    "application",
    "activity",
    "activity-alias",
    "service",
    "receiver",
    "provider",
}


def _register_namespaces(manifest_text: str) -> None:
    """Registra todos los prefijos xmlns del manifest para conservarlos al escribir."""
    for prefix, uri in re.findall(r'xmlns:([\w-]+)="([^"]+)"', manifest_text):
        ET.register_namespace(prefix, uri)
    default = re.search(r'xmlns="([^"]+)"', manifest_text)
    if default:
        ET.register_namespace("", default.group(1))


def _manifest_path(decoded_dir: str) -> str:
    return os.path.join(decoded_dir, "AndroidManifest.xml")


def read_info(decoded_dir: str) -> tuple[str, str]:
    """Devuelve (package_name, app_name) leídos del APK decodificado."""
    text = open(_manifest_path(decoded_dir), encoding="utf-8").read()
    _register_namespaces(text)
    root = ET.fromstring(text)

    package = root.get("package", "")

    label = ""
    app = root.find("application")
    if app is not None:
        label = app.get(f"{_AND}label", "")
    app_name = _resolve_label(decoded_dir, label) or package
    return package, app_name


def _resolve_label(decoded_dir: str, label: str) -> str:
    """Resuelve un label tipo @string/app_name leyendo los strings.xml."""
    if not label.startswith("@string/"):
        return label
    name = label.split("/", 1)[1]
    for sx in glob.glob(os.path.join(decoded_dir, "res", "values*", "strings.xml")):
        try:
            tree = ET.parse(sx)
        except ET.ParseError:
            continue
        for node in tree.getroot().findall("string"):
            if node.get("name") == name:
                return (node.text or "").strip()
    return label


def set_app_name(decoded_dir: str, new_name: str) -> None:
    """Cambia el nombre visible de la app."""
    path = _manifest_path(decoded_dir)
    text = open(path, encoding="utf-8").read()
    _register_namespaces(text)
    root = ET.fromstring(text)
    app = root.find("application")
    if app is None:
        return
    label = app.get(f"{_AND}label", "")

    if label.startswith("@string/"):
        # El nombre vive en strings.xml: actualizamos todas sus variantes.
        name = label.split("/", 1)[1]
        _update_string_resource(decoded_dir, name, new_name)
    else:
        # Nombre literal en el manifest.
        app.set(f"{_AND}label", new_name)
        _write_manifest(root, path)


def _update_string_resource(decoded_dir: str, key: str, value: str) -> None:
    changed = False
    for sx in glob.glob(os.path.join(decoded_dir, "res", "values*", "strings.xml")):
        try:
            tree = ET.parse(sx)
        except ET.ParseError:
            continue
        node_changed = False
        for node in tree.getroot().findall("string"):
            if node.get("name") == key:
                node.text = value
                node_changed = True
        if node_changed:
            tree.write(sx, encoding="utf-8", xml_declaration=True)
            changed = True
    if not changed:
        # No existía: lo creamos en el strings.xml por defecto.
        default = os.path.join(decoded_dir, "res", "values", "strings.xml")
        os.makedirs(os.path.dirname(default), exist_ok=True)
        if os.path.isfile(default):
            tree = ET.parse(default)
            root = tree.getroot()
        else:
            root = ET.Element("resources")
            tree = ET.ElementTree(root)
        el = ET.SubElement(root, "string", {"name": key})
        el.text = value
        tree.write(default, encoding="utf-8", xml_declaration=True)


def set_package_name(decoded_dir: str, new_package: str, log=None) -> str:
    """Cambia el package name (application ID). Devuelve el package anterior."""
    path = _manifest_path(decoded_dir)
    text = open(path, encoding="utf-8").read()
    _register_namespaces(text)
    root = ET.fromstring(text)
    old_package = root.get("package", "")
    if not old_package:
        raise RuntimeError("El manifest no declara un package.")

    # 1) Expandimos nombres de componentes relativos al package ANTIGUO.
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag not in _COMPONENT_TAGS:
            continue
        for attr in (f"{_AND}name", f"{_AND}targetActivity"):
            val = el.get(attr)
            if val:
                el.set(attr, _absolute_class(old_package, val))

    # 2) Renombramos authorities y permisos propios ligados al package viejo.
    renamed = _rename_unique_names(root, old_package, new_package)

    # 3) Cambiamos el package del manifest al nuevo.
    root.set("package", new_package)
    _write_manifest(root, path)
    if log:
        for kind, old, new in renamed:
            log(f"   {kind}: {old} -> {new}")
    return old_package


# Atributos que contienen nombres de permiso.
_PERMISSION_ATTRS = ("permission", "readPermission", "writePermission")
_PERMISSION_DECL_TAGS = {"permission", "permission-group", "permission-tree"}
_PERMISSION_USE_TAGS = {"uses-permission", "uses-permission-sdk-23"}


def _swap_prefix(value: str, old: str, new: str) -> str:
    if value == old:
        return new
    if value.startswith(old + "."):
        return new + value[len(old):]
    return value


def _rename_unique_names(
    root: ET.Element, old: str, new: str
) -> list[tuple[str, str, str]]:
    """Cambia authorities y permisos propios `old.*` -> `new.*`."""
    changes: list[tuple[str, str, str]] = []

    def swap(el: ET.Element, attr: str, kind: str) -> None:
        val = el.get(f"{_AND}{attr}")
        if not val:
            return
        if attr == "authorities":
            parts = val.split(";")
            new_val = ";".join(_swap_prefix(p.strip(), old, new) for p in parts)
        else:
            new_val = _swap_prefix(val, old, new)
        if new_val != val:
            el.set(f"{_AND}{attr}", new_val)
            changes.append((kind, val, new_val))

    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag == "provider":
            swap(el, "authorities", "provider")
        if tag in _PERMISSION_DECL_TAGS or tag in _PERMISSION_USE_TAGS:
            swap(el, "name", "permiso")
        if tag == "permission":
            swap(el, "permissionGroup", "grupo de permisos")
        for attr in _PERMISSION_ATTRS:
            swap(el, attr, "permiso requerido")
    return changes


def _absolute_class(package: str, name: str) -> str:
    if name.startswith("."):
        return package + name
    if "." not in name:
        return f"{package}.{name}"
    return name  # ya es un nombre totalmente cualificado


# ------------------------------------------------------------ versión ---
#
# Al decodificar, apktool saca versionCode/versionName del manifest y los
# guarda en apktool.yml (bloque `versionInfo`), y al reconstruir se los pasa a
# aapt. Pero el lector YAML de apktool 2.9.x es muy limitado: corta el valor
# en el primer ':' y elimina las comillas. Para admitir cualquier texto, el
# valor nuevo se escribe en el AndroidManifest.xml (XML escapa todo bien) y la
# clave correspondiente de apktool.yml se pone a `null`, de modo que aapt use
# el valor del manifest.

MAX_VERSION_CODE = 2_100_000_000  # límite que impone Google Play / Android


def _yml_path(decoded_dir: str) -> str:
    return os.path.join(decoded_dir, "apktool.yml")


def _yaml_value(raw: str) -> str:
    value = raw.strip()
    if value in ("", "null", "~"):
        return ""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    # apktool escapa como XML los valores que vuelca (&quot;, &amp;, ...).
    return html.unescape(value)


_VERSION_LINE = re.compile(r"^(\s+)(versionCode|versionName):(.*)$")


def read_version(decoded_dir: str) -> tuple[str, str]:
    """Devuelve (versionCode, versionName) del APK decodificado ('' si falta)."""
    code = name = ""
    yml = _yml_path(decoded_dir)
    if os.path.isfile(yml):
        in_block = False
        for line in open(yml, encoding="utf-8").read().splitlines():
            if line and not line[0].isspace():
                in_block = line.rstrip() == "versionInfo:"
                continue
            m = _VERSION_LINE.match(line)
            if in_block and m:
                if m.group(2) == "versionCode":
                    code = _yaml_value(m.group(3))
                else:
                    name = _yaml_value(m.group(3))

    # El manifest tiene prioridad si declara los atributos.
    root = ET.fromstring(open(_manifest_path(decoded_dir), encoding="utf-8").read())
    code = root.get(f"{_AND}versionCode") or code
    name = root.get(f"{_AND}versionName") or name
    return code, name


def set_version(
    decoded_dir: str,
    version_code: str | None,
    version_name: str | None,
) -> None:
    """Cambia versionCode y/o versionName. None = dejar el valor actual."""
    if version_code is None and version_name is None:
        return
    if version_code is not None:
        version_code = version_code.strip()
        if not version_code.isdigit() or not 0 < int(version_code) <= MAX_VERSION_CODE:
            raise ValueError(
                f"versionCode debe ser un entero entre 1 y {MAX_VERSION_CODE}."
            )
        version_code = str(int(version_code))
    if version_name is not None:
        version_name = version_name.strip()
        if not version_name:
            raise ValueError("versionName no puede estar vacío.")

    changes = {"versionCode": version_code, "versionName": version_name}
    changes = {k: v for k, v in changes.items() if v is not None}

    # 1) Manifest: aquí vive el valor nuevo.
    path = _manifest_path(decoded_dir)
    text = open(path, encoding="utf-8").read()
    _register_namespaces(text)
    root = ET.fromstring(text)
    for attr, value in changes.items():
        root.set(f"{_AND}{attr}", value)
    _write_manifest(root, path)

    # 2) apktool.yml: anulamos esas claves para que no pisen al manifest.
    yml = _yml_path(decoded_dir)
    if not os.path.isfile(yml):
        return
    lines = open(yml, encoding="utf-8").read().splitlines()
    in_block = False
    for i, line in enumerate(lines):
        if line and not line[0].isspace():
            in_block = line.rstrip() == "versionInfo:"
            continue
        m = _VERSION_LINE.match(line)
        if in_block and m and m.group(2) in changes:
            lines[i] = f"{m.group(1)}{m.group(2)}: null"
    with open(yml, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def _write_manifest(root: ET.Element, path: str) -> None:
    body = ET.tostring(root, encoding="unicode")
    with open(path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="utf-8" standalone="no"?>\n')
        f.write(body)
