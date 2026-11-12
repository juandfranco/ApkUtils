"""
Interfaz gráfica (Tkinter, solo librería estándar) para renombrar APKs.
"""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import apk_tools, pipeline, renamer, signing

APP_TITLE = "APK Renamer"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("760x880")
        self.minsize(680, 800)

        self._log_queue: queue.Queue[str] = queue.Queue()
        self._busy = False

        self._build_ui()
        self._refresh_tool_status()
        self.after(100, self._drain_log)

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

        # Firma del APK cargado
        ttk.Label(frm, text="Firma del APK:").grid(row=6, column=0, sticky="nw", **pad)
        self.input_sig_var = tk.StringVar(value="(pulsa 'Cargar datos del APK')")
        ttk.Label(frm, textvariable=self.input_sig_var, wraplength=560, justify="left").grid(
            row=6, column=1, columnspan=2, sticky="w", **pad
        )

        # Clave con la que se firma el APK de salida
        self._build_signing(frm, row=7, pad=pad)

        # APK de salida
        ttk.Label(frm, text="APK de salida:").grid(row=8, column=0, sticky="w", **pad)
        self.out_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.out_var).grid(row=8, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Examinar…", command=self._browse_out).grid(row=8, column=2, **pad)

        # Acción principal
        self.run_btn = ttk.Button(frm, text="Procesar APK", command=self._run)
        self.run_btn.grid(row=9, column=1, sticky="w", **pad)

        # Log
        ttk.Label(frm, text="Registro:").grid(row=10, column=0, sticky="w", **pad)
        self.log_text = tk.Text(frm, height=10, wrap="word", state="disabled")
        self.log_text.grid(row=11, column=0, columnspan=3, sticky="nsew", **pad)
        frm.rowconfigure(11, weight=1)

        # Barra de estado
        self.status_var = tk.StringVar()
        bar = ttk.Frame(frm)
        bar.grid(row=12, column=0, columnspan=3, sticky="ew", **pad)
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

    # ------------------------------------------------------------ helpers ---
    def _browse_apk(self) -> None:
        path = filedialog.askopenfilename(
            title="Selecciona un APK", filetypes=[("APK", "*.apk"), ("Todos", "*.*")]
        )
        if path:
            self.apk_var.set(path)
            if not self.out_var.get():
                base, ext = os.path.splitext(path)
                self.out_var.set(f"{base}_renombrado{ext}")

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
        path = filedialog.asksaveasfilename(
            title="Guardar APK como", defaultextension=".apk",
            filetypes=[("APK", "*.apk")],
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

            def fill() -> None:
                self.pkg_var.set(info.package)
                self.name_var.set(info.name)
                self.vcode_var.set(info.version_code)
                self.vname_var.set(info.version_name)

            self.after(0, fill)
            self.log(f"Package actual: {info.package}")
            self.log(f"Nombre actual: {info.name}")
            self.log(f"versionCode actual: {info.version_code or '(no definido)'}")
            self.log(f"versionName actual: {info.version_name or '(no definido)'}")
            who = signing.identify(info.signer_sha256)
            sig = f"{who}\nSHA-256: {info.signer_sha256 or '-'}"
            self.after(0, lambda: self.input_sig_var.set(sig))
            self.log(f"Firmado con: {who}")
            self.log(f"   SHA-256: {info.signer_sha256 or '-'}")

        self._run_in_thread(task)

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
        if not (new_name or new_pkg or new_vcode is not None or new_vname is not None):
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

        def task() -> None:
            apk_tools.ensure_tools(self.log)
            key = signing.resolve_key(*params)
            result = pipeline.process(
                apk, out, new_name, new_pkg, self.log,
                new_version_code=new_vcode, new_version_name=new_vname,
                key=key,
            )
            self.after(
                0,
                lambda: messagebox.showinfo(APP_TITLE, f"APK generado:\n{result}"),
            )

        self._run_in_thread(task)


def _valid_package(pkg: str) -> bool:
    import re

    return bool(re.fullmatch(r"[a-zA-Z][\w]*(\.[a-zA-Z][\w]*)+", pkg))


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
