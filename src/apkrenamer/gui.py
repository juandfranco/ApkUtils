"""
Interfaz gráfica (Tkinter, solo librería estándar) para renombrar APKs.
"""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import apk_tools, permissions, pipeline, renamer, settings, signing

APP_TITLE = "APK Renamer"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("760x910")
        self.minsize(680, 830)

        self._log_queue: queue.Queue[str] = queue.Queue()
        self._busy = False
        self._settings = settings.load()
        self._loaded_package: str | None = None  # package ORIGINAL del APK cargado
        self._apk_permissions: list[permissions.Permission] = []
        self._remove_perms: set[str] = set()

        self._build_ui()
        self._restore_general()
        self._refresh_tool_status()
        self.after(100, self._drain_log)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------------------------------------------------------- UI ---
    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        # APK de entrada
        ttk.Label(frm, text="APK de entrada:").grid(row=0, column=0, sticky="w", **pad)
        self.apk_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.apk_var).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Examinar…", command=self._browse_apk).grid(row=0, column=2, **pad)

        ttk.Button(frm, text="Cargar datos del APK", command=self._load_info).grid(
            row=1, column=1, sticky="w", **pad
        )

        # Nombre visible
        self.name_enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            frm, text="Cambiar nombre visible:", variable=self.name_enabled
        ).grid(row=2, column=0, sticky="w", **pad)
        self.name_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.name_var).grid(row=2, column=1, columnspan=2, sticky="ew", **pad)

        # Package name
        self.pkg_enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            frm, text="Cambiar package name:", variable=self.pkg_enabled
        ).grid(row=3, column=0, sticky="w", **pad)
        self.pkg_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.pkg_var).grid(row=3, column=1, columnspan=2, sticky="ew", **pad)

        # Versión (desactivada por defecto: solo se cambia si se pide).
        self.vcode_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frm, text="Cambiar versionCode:", variable=self.vcode_enabled
        ).grid(row=4, column=0, sticky="w", **pad)
        self.vcode_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.vcode_var).grid(row=4, column=1, columnspan=2, sticky="ew", **pad)

        self.vname_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frm, text="Cambiar versionName:", variable=self.vname_enabled
        ).grid(row=5, column=0, sticky="w", **pad)
        self.vname_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.vname_var).grid(row=5, column=1, columnspan=2, sticky="ew", **pad)

        # Permisos
        ttk.Label(frm, text="Permisos:").grid(row=6, column=0, sticky="w", **pad)
        perm_row = ttk.Frame(frm)
        perm_row.grid(row=6, column=1, columnspan=2, sticky="ew", **pad)
        self.perm_btn = ttk.Button(perm_row, text="Elegir permisos…", command=self._edit_permissions)
        self.perm_btn.grid(row=0, column=0, sticky="w")
        self.perm_summary_var = tk.StringVar(value="(se leen al cargar el APK)")
        ttk.Label(perm_row, textvariable=self.perm_summary_var).grid(row=0, column=1, sticky="w", padx=8)

        # Firma del APK cargado
        ttk.Label(frm, text="Firma del APK:").grid(row=7, column=0, sticky="nw", **pad)
        self.input_sig_var = tk.StringVar(value="(pulsa 'Cargar datos del APK')")
        ttk.Label(frm, textvariable=self.input_sig_var, wraplength=560, justify="left").grid(
            row=7, column=1, columnspan=2, sticky="w", **pad
        )

        # Clave con la que se firma el APK de salida
        self._build_signing(frm, row=8, pad=pad)

        # APK de salida
        ttk.Label(frm, text="APK de salida:").grid(row=9, column=0, sticky="w", **pad)
        self.out_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.out_var).grid(row=9, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Examinar…", command=self._browse_out).grid(row=9, column=2, **pad)

        # Acción principal
        self.run_btn = ttk.Button(frm, text="Procesar APK", command=self._run)
        self.run_btn.grid(row=10, column=1, sticky="w", **pad)

        # Log
        ttk.Label(frm, text="Registro:").grid(row=11, column=0, sticky="w", **pad)
        self.log_text = tk.Text(frm, height=10, wrap="word", state="disabled")
        self.log_text.grid(row=12, column=0, columnspan=3, sticky="nsew", **pad)
        frm.rowconfigure(12, weight=1)

        # Barra de estado
        self.status_var = tk.StringVar()
        bar = ttk.Frame(frm)
        bar.grid(row=13, column=0, columnspan=3, sticky="ew", **pad)
        bar.columnconfigure(0, weight=1)
        ttk.Label(bar, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        ttk.Button(
            bar, text="Descargar Java + herramientas", command=self._download_tools
        ).grid(row=0, column=1, sticky="e")

    def _build_signing(self, parent: ttk.Frame, row: int, pad: dict) -> None:
        box = ttk.LabelFrame(parent, text="Firmar el APK de salida con", padding=6)
        box.grid(row=row, column=0, columnspan=3, sticky="ew", **pad)
        box.columnconfigure(1, weight=1)

        self.key_source = tk.StringVar(value=signing.default_source())
        has_pc = os.path.isfile(signing.pc_debug_keystore())
        pc_text = signing.SOURCE_LABELS[signing.SOURCE_PC]
        if not has_pc:
            pc_text += "  (no existe en este PC)"
        options = [
            (signing.SOURCE_PC, pc_text, has_pc),
            (signing.SOURCE_EMBEDDED, signing.SOURCE_LABELS[signing.SOURCE_EMBEDDED], True),
            (signing.SOURCE_CUSTOM, signing.SOURCE_LABELS[signing.SOURCE_CUSTOM] + ":", True),
        ]
        for i, (value, text, enabled) in enumerate(options):
            rb = ttk.Radiobutton(
                box, text=text, value=value, variable=self.key_source,
                command=self._on_key_change,
            )
            rb.grid(row=i, column=0, columnspan=3 if i < 2 else 1, sticky="w")
            if not enabled:
                rb.state(["disabled"])

        # Keystore propio
        self.ks_path_var = tk.StringVar()
        self.ks_alias_var = tk.StringVar()
        self.ks_pass_var = tk.StringVar()
        self.ks_keypass_var = tk.StringVar()
        self._custom_widgets: list[ttk.Widget] = []
        e = ttk.Entry(box, textvariable=self.ks_path_var)
        e.grid(row=2, column=1, sticky="ew", padx=4)
        b = ttk.Button(box, text="Examinar…", command=self._browse_keystore)
        b.grid(row=2, column=2, padx=4)
        self._custom_widgets += [e, b]
        fields = ttk.Frame(box)
        fields.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(2, 0))
        for col, (text, var, show) in enumerate([
            ("Alias (vacío = automático):", self.ks_alias_var, ""),
            ("Contraseña:", self.ks_pass_var, "*"),
            ("Contraseña de la clave:", self.ks_keypass_var, "*"),
        ]):
            ttk.Label(fields, text=text).grid(row=0, column=col * 2, sticky="w", padx=(12, 2))
            w = ttk.Entry(fields, textvariable=var, show=show, width=14)
            w.grid(row=0, column=col * 2 + 1, sticky="w")
            self._custom_widgets.append(w)
        self.remember_pass = tk.BooleanVar(value=False)
        cb = ttk.Checkbutton(
            fields, text="Recordar contraseña (se guarda cifrada en este PC)",
            variable=self.remember_pass,
        )
        cb.grid(row=1, column=0, columnspan=6, sticky="w", padx=(12, 0), pady=(2, 0))
        if not settings.can_encrypt():
            cb.state(["disabled"])
        self._custom_widgets.append(cb)

        # Huella y origen de la clave elegida
        self.key_info_var = tk.StringVar()
        ttk.Label(box, textvariable=self.key_info_var, wraplength=680, justify="left").grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(6, 2)
        )
        btns = ttk.Frame(box)
        btns.grid(row=5, column=0, columnspan=3, sticky="w")
        ttk.Button(btns, text="Ver huella y origen", command=self._show_key_info).grid(
            row=0, column=0, padx=(0, 6)
        )
        ttk.Button(btns, text="Exportar esta clave…", command=self._export_key).grid(
            row=0, column=1
        )
        self._on_key_change()

    # ---------------------------------------------------------- ajustes ---
    def _general(self) -> dict:
        return self._settings["general"]

    def _restore_general(self) -> None:
        """Vuelve a poner la clave y el keystore usados la última vez."""
        g = self._general()
        self._apply_key_settings(g)
        if g.get("remember_pass"):
            self.remember_pass.set(True)
            self.ks_pass_var.set(settings.decrypt(g.get("ks_pass")))
            self.ks_keypass_var.set(settings.decrypt(g.get("ks_keypass")))

    def _apply_key_settings(self, d: dict) -> None:
        source = d.get("key_source")
        if source == signing.SOURCE_PC and not os.path.isfile(signing.pc_debug_keystore()):
            source = None
        if source in signing.SOURCE_LABELS:
            self.key_source.set(source)
        if d.get("ks_path"):
            self.ks_path_var.set(d["ks_path"])
            self.ks_alias_var.set(d.get("ks_alias", ""))
        self._on_key_change()

    def _key_settings(self) -> dict:
        return {
            "key_source": self.key_source.get(),
            "ks_path": self.ks_path_var.get().strip(),
            "ks_alias": self.ks_alias_var.get().strip(),
        }

    def _save_general(self) -> None:
        g = self._general()
        g.update(self._key_settings())
        remember = bool(self.remember_pass.get())
        g["remember_pass"] = remember
        g["ks_pass"] = settings.encrypt(self.ks_pass_var.get()) if remember else None
        g["ks_keypass"] = settings.encrypt(self.ks_keypass_var.get()) if remember else None
        try:
            settings.save(self._settings)
        except OSError as exc:
            self.log(f"AVISO: no se pudieron guardar los ajustes: {exc}")

    def _on_close(self) -> None:
        self._save_general()
        self.destroy()

    def _suggest_output(self, apk_path: str, out_dir: str | None = None) -> None:
        base, ext = os.path.splitext(os.path.basename(apk_path))
        folder = out_dir if out_dir and os.path.isdir(out_dir) else os.path.dirname(apk_path)
        self.out_var.set(os.path.join(folder, f"{base}_renombrado{ext}").replace("\\", "/"))

    # ------------------------------------------------------------ helpers ---
    def _browse_apk(self) -> None:
        path = filedialog.askopenfilename(
            title="Selecciona un APK", filetypes=[("APK", "*.apk"), ("Todos", "*.*")],
            initialdir=self._general().get("in_dir") or None,
        )
        if path:
            self.apk_var.set(path)
            self._general()["in_dir"] = os.path.dirname(path)
            self._loaded_package = None
            self._apk_permissions = []
            self._set_removed(set())
            self._suggest_output(path)
            self._load_info()

    def _browse_keystore(self) -> None:
        path = filedialog.askopenfilename(
            title="Selecciona un keystore",
            filetypes=[("Keystore", "*.jks *.keystore *.p12 *.pfx"), ("Todos", "*.*")],
        )
        if path:
            self.ks_path_var.set(path)
            self.key_source.set(signing.SOURCE_CUSTOM)
            self._on_key_change()

    def _on_key_change(self) -> None:
        custom = self.key_source.get() == signing.SOURCE_CUSTOM
        for w in self._custom_widgets:
            w.state(["!disabled"] if custom else ["disabled"])
        self.key_info_var.set("Pulsa 'Ver huella y origen' para ver de dónde sale la clave.")

    def _key_params(self) -> tuple[str, str, str, str, str]:
        """Lee la clave elegida (en el hilo de la UI); se resuelve luego en segundo plano."""
        return (
            self.key_source.get(),
            self.ks_path_var.get().strip(),
            self.ks_alias_var.get(),
            self.ks_pass_var.get(),
            self.ks_keypass_var.get(),
        )

    def _browse_out(self) -> None:
        current = self.out_var.get().strip()
        path = filedialog.asksaveasfilename(
            title="Guardar APK como", defaultextension=".apk",
            filetypes=[("APK", "*.apk")],
            initialdir=os.path.dirname(current) if current else None,
            initialfile=os.path.basename(current) if current else "",
        )
        if path:
            self.out_var.set(path)

    def log(self, msg: str) -> None:
        self._log_queue.put(str(msg))

    def _drain_log(self) -> None:
        try:
            while True:
                msg = self._log_queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", msg + "\n")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._drain_log)

    def _refresh_tool_status(self) -> None:
        st = apk_tools.check_tools()
        parts = []
        parts.append("Java: OK" if st.java else "Java: se descargará")
        parts.append("apktool: OK" if st.apktool else "apktool: se descargará")
        parts.append("firmador: OK" if st.signer else "firmador: se descargará")
        self.status_var.set("   |   ".join(parts))

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.run_btn.configure(state="disabled" if busy else "normal")

    def _run_in_thread(self, target) -> None:
        if self._busy:
            return
        self._set_busy(True)

        def wrapper() -> None:
            try:
                target()
            except Exception as exc:  # noqa: BLE001 - mostramos cualquier error
                self.log(f"ERROR: {exc}")
                self.after(0, lambda: messagebox.showerror(APP_TITLE, str(exc)))
            finally:
                self.after(0, lambda: self._set_busy(False))
                self.after(0, self._refresh_tool_status)

        threading.Thread(target=wrapper, daemon=True).start()

    # ------------------------------------------------------------ actions ---
    def _show_key_info(self) -> None:
        params = self._key_params()

        def task() -> None:
            apk_tools.ensure_tools(self.log)
            key = signing.resolve_key(*params)
            info = signing.keystore_info(key)
            text = (
                f"Origen: {key.keystore}\n"
                f"Alias: {info.alias}   Titular: {info.owner}\n"
                f"SHA-256: {info.sha256}"
            )
            self.after(0, lambda: self.key_info_var.set(text))
            self.log(f"Clave elegida: {key.label}")
            for line in text.splitlines():
                self.log("   " + line)

        self._run_in_thread(task)

    def _export_key(self) -> None:
        dest = filedialog.askdirectory(title="Carpeta donde exportar la clave")
        if not dest:
            return

        params = self._key_params()

        def task() -> None:
            apk_tools.ensure_tools(self.log)
            path = signing.export_key(signing.resolve_key(*params), dest)
            self.log(f"Clave exportada: {path}")
            self.log(f"   (con sus datos en {os.path.basename(path)}.LEEME.txt)")
            self.after(
                0, lambda: messagebox.showinfo(APP_TITLE, f"Clave exportada en:\n{path}")
            )

        self._run_in_thread(task)

    def _download_tools(self) -> None:
        self._run_in_thread(lambda: apk_tools.ensure_tools(self.log))

    def _load_info(self) -> None:
        apk = self.apk_var.get().strip()
        if not apk or not os.path.isfile(apk):
            messagebox.showwarning(APP_TITLE, "Selecciona un APK válido primero.")
            return

        def task() -> None:
            info = pipeline.load_apk_info(apk, self.log)
            profile = self._settings["apps"].get(info.package)

            def fill() -> None:
                self._loaded_package = info.package
                self.pkg_var.set(info.package)
                self.name_var.set(info.name)
                self.vcode_var.set(info.version_code)
                self.vname_var.set(info.version_name)
                self._apk_permissions = list(info.permissions)
                self._set_removed(set())
                if profile:
                    self._apply_profile(profile, apk)

            self.after(0, fill)
            self.log(f"Package actual: {info.package}")
            self.log(f"Nombre actual: {info.name}")
            self.log(f"versionCode actual: {info.version_code or '(no definido)'}")
            self.log(f"versionName actual: {info.version_name or '(no definido)'}")
            self.log(f"Permisos: {len(info.permissions)}")
            who = signing.identify(info.signer_sha256)
            sig = f"{who}\nSHA-256: {info.signer_sha256 or '-'}"
            self.after(0, lambda: self.input_sig_var.set(sig))
            self.log(f"Firmado con: {who}")
            self.log(f"   SHA-256: {info.signer_sha256 or '-'}")
            if profile:
                self.log(f"== Ajustes guardados para {info.package} aplicados ==")
                self.log(f"   nombre: {profile.get('name') or '(sin cambio)'}   "
                         f"package: {profile.get('package') or '(sin cambio)'}")
                self.log(f"   firma: {signing.SOURCE_LABELS.get(profile.get('key_source'), '?')}")
                if profile.get("remove_permissions"):
                    self.log(f"   permisos a quitar: {len(profile['remove_permissions'])}")

        self._run_in_thread(task)

    def _update_perm_summary(self) -> None:
        total = len(self._apk_permissions)
        if not total:
            self.perm_summary_var.set("(se leen al cargar el APK)")
            return
        n = len(self._remove_perms)
        dangerous = sum(p.kind == permissions.KIND_DANGEROUS for p in self._apk_permissions)
        text = f"{total} permisos ({dangerous} peligrosos)"
        text += f"  ·  se quitarán {n}" if n else "  ·  no se quita ninguno"
        self.perm_summary_var.set(text)

    def _edit_permissions(self) -> None:
        if not self._apk_permissions:
            messagebox.showinfo(APP_TITLE, "Carga primero un APK para ver sus permisos.")
            return
        PermissionsDialog(self, self._apk_permissions, self._remove_perms, self._set_removed)

    def _set_removed(self, removed: set[str]) -> None:
        self._remove_perms = set(removed)
        self._update_perm_summary()

    def _apply_profile(self, profile: dict, apk: str) -> None:
        """Rellena el formulario con lo usado la última vez para esta app."""
        self.name_enabled.set(bool(profile.get("name_enabled", True)))
        self.pkg_enabled.set(bool(profile.get("pkg_enabled", True)))
        if profile.get("name"):
            self.name_var.set(profile["name"])
        if profile.get("package"):
            self.pkg_var.set(profile["package"])
        self._apply_key_settings(profile)
        self._suggest_output(apk, profile.get("out_dir"))
        present = {p.name for p in self._apk_permissions}
        self._set_removed(set(profile.get("remove_permissions", [])) & present)

    def _save_profile(self, original_package: str, out: str) -> None:
        profile = {
            "name": self.name_var.get().strip(),
            "package": self.pkg_var.get().strip(),
            "name_enabled": bool(self.name_enabled.get()),
            "pkg_enabled": bool(self.pkg_enabled.get()),
            "out_dir": os.path.dirname(os.path.abspath(out)),
            "remove_permissions": sorted(self._remove_perms),
            **self._key_settings(),
        }
        self._settings["apps"][original_package] = profile
        self._save_general()

    def _run(self) -> None:
        apk = self.apk_var.get().strip()
        out = self.out_var.get().strip()
        if not apk or not os.path.isfile(apk):
            messagebox.showwarning(APP_TITLE, "Selecciona un APK válido.")
            return
        if not out:
            messagebox.showwarning(APP_TITLE, "Indica la ruta del APK de salida.")
            return

        new_name = self.name_var.get().strip() if self.name_enabled.get() else None
        new_pkg = self.pkg_var.get().strip() if self.pkg_enabled.get() else None
        new_vcode = self.vcode_var.get().strip() if self.vcode_enabled.get() else None
        new_vname = self.vname_var.get().strip() if self.vname_enabled.get() else None
        remove_perms = sorted(self._remove_perms)
        if not (new_name or new_pkg or new_vcode is not None or new_vname is not None
                or remove_perms):
            messagebox.showwarning(APP_TITLE, "Activa al menos un cambio.")
            return
        if new_vcode is not None and not (
            new_vcode.isdigit() and 0 < int(new_vcode) <= renamer.MAX_VERSION_CODE
        ):
            messagebox.showwarning(
                APP_TITLE,
                f"El versionCode debe ser un número entero entre 1 y "
                f"{renamer.MAX_VERSION_CODE}.",
            )
            return
        if new_vname is not None and not new_vname:
            messagebox.showwarning(APP_TITLE, "El versionName no puede estar vacío.")
            return
        if new_pkg and not _valid_package(new_pkg):
            messagebox.showwarning(
                APP_TITLE,
                "El package name no es válido. Usa el formato com.empresa.app",
            )
            return

        params = self._key_params()
        original_package = self._loaded_package

        def task() -> None:
            apk_tools.ensure_tools(self.log)
            key = signing.resolve_key(*params)
            orig = original_package or pipeline.load_apk_info(apk, lambda *_: None).package
            result = pipeline.process(
                apk, out, new_name, new_pkg, self.log,
                new_version_code=new_vcode, new_version_name=new_vname,
                key=key,
                remove_permissions=remove_perms,
            )

            def done() -> None:
                self._save_profile(orig, result)
                self.log(f"Ajustes guardados para la próxima vez ({orig}).")
                messagebox.showinfo(APP_TITLE, f"APK generado:\n{result}")

            self.after(0, done)

        self._run_in_thread(task)


class PermissionsDialog(tk.Toplevel):
    """Lista de permisos con casillas: marcada = se mantiene."""

    _KIND_TEXT = {
        permissions.KIND_DANGEROUS: "PELIGROSO",
        permissions.KIND_SPECIAL: "especial",
        permissions.KIND_NORMAL: "",
    }

    def __init__(self, master, perms, removed: set[str], on_accept) -> None:
        super().__init__(master)
        self.title("Permisos del APK")
        self.geometry("640x560")
        self.transient(master)
        self.grab_set()
        self._on_accept = on_accept
        order = {permissions.KIND_DANGEROUS: 0, permissions.KIND_SPECIAL: 1,
                 permissions.KIND_NORMAL: 2}
        self._perms = sorted(perms, key=lambda p: (order[p.kind], p.name))
        self._vars: dict[str, tk.BooleanVar] = {}

        ttk.Label(
            self, padding=(10, 8, 10, 4), wraplength=600, justify="left",
            text=("Desmarca los permisos que quieras QUITAR. Los peligrosos suelen poder "
                  "quitarse sin problema; los marcados con ⚠ la app suele necesitarlos y "
                  "quitarlos puede hacer que se cierre."),
        ).pack(fill="x")

        outer = ttk.Frame(self, padding=(10, 0))
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-e.delta // 120, "units"))
        self.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

        for i, p in enumerate(self._perms):
            var = tk.BooleanVar(value=p.name not in removed)
            self._vars[p.name] = var
            ttk.Checkbutton(inner, variable=var, text=p.short if p.is_android else p.name).grid(
                row=i, column=0, sticky="w"
            )
            tag = self._KIND_TEXT[p.kind] + ("  ⚠ necesario" if p.risky_to_remove else "")
            ttk.Label(inner, text=tag, foreground="#b00020" if p.kind != "normal" else "#8a6d00").grid(
                row=i, column=1, sticky="w", padx=12
            )

        btns = ttk.Frame(self, padding=10)
        btns.pack(fill="x")
        ttk.Button(btns, text="Quitar todos los peligrosos", command=self._drop_dangerous).pack(side="left")
        ttk.Button(btns, text="Mantener todos", command=self._keep_all).pack(side="left", padx=6)
        ttk.Button(btns, text="Aceptar", command=self._accept).pack(side="right")
        ttk.Button(btns, text="Cancelar", command=self.destroy).pack(side="right", padx=6)

    def _drop_dangerous(self) -> None:
        for p in self._perms:
            if p.kind == permissions.KIND_DANGEROUS:
                self._vars[p.name].set(False)

    def _keep_all(self) -> None:
        for v in self._vars.values():
            v.set(True)

    def _accept(self) -> None:
        removed = {name for name, v in self._vars.items() if not v.get()}
        risky = [p.short for p in self._perms if p.name in removed and p.risky_to_remove]
        if risky and not messagebox.askyesno(
            APP_TITLE,
            "Vas a quitar permisos que la app suele necesitar:\n\n  "
            + "\n  ".join(risky)
            + "\n\nLa app podría cerrarse al abrirla. ¿Quitarlos igualmente?",
            parent=self,
        ):
            return
        self._on_accept(removed)
        self.destroy()


def _valid_package(pkg: str) -> bool:
    import re

    return bool(re.fullmatch(r"[a-zA-Z][\w]*(\.[a-zA-Z][\w]*)+", pkg))


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
