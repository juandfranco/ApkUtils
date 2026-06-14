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
"""

from __future__ import annotations

import glob
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


def set_package_name(decoded_dir: str, new_package: str) -> str:
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

    # 2) Cambiamos el package del manifest al nuevo.
    root.set("package", new_package)
    _write_manifest(root, path)
    return old_package


def _absolute_class(package: str, name: str) -> str:
    if name.startswith("."):
        return package + name
    if "." not in name:
        return f"{package}.{name}"
    return name  # ya es un nombre totalmente cualificado


def _write_manifest(root: ET.Element, path: str) -> None:
    body = ET.tostring(root, encoding="unicode")
    with open(path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="utf-8" standalone="no"?>\n')
        f.write(body)
