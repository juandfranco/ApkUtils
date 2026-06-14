"""
Interfaz gráfica (Tkinter, solo librería estándar) para renombrar APKs.
"""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import apk_tools, pipeline

APP_TITLE = "APK Renamer"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("720x600")
        self.minsize(640, 520)

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

        # APK de salida
        ttk.Label(frm, text="APK de salida:").grid(row=4, column=0, sticky="w", **pad)
        self.out_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.out_var).grid(row=4, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Examinar…", command=self._browse_out).grid(row=4, column=2, **pad)

        # Acción principal
        self.run_btn = ttk.Button(frm, text="Procesar APK", command=self._run)
        self.run_btn.grid(row=5, column=1, sticky="w", **pad)

        # Log
        ttk.Label(frm, text="Registro:").grid(row=6, column=0, sticky="w", **pad)
        self.log_text = tk.Text(frm, height=14, wrap="word", state="disabled")
        self.log_text.grid(row=7, column=0, columnspan=3, sticky="nsew", **pad)
        frm.rowconfigure(7, weight=1)

        # Barra de estado
        self.status_var = tk.StringVar()
        bar = ttk.Frame(frm)
        bar.grid(row=8, column=0, columnspan=3, sticky="ew", **pad)
        bar.columnconfigure(0, weight=1)
        ttk.Label(bar, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        ttk.Button(
            bar, text="Descargar Java + herramientas", command=self._download_tools
        ).grid(row=0, column=1, sticky="e")

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
    def _download_tools(self) -> None:
        self._run_in_thread(lambda: apk_tools.ensure_tools(self.log))

    def _load_info(self) -> None:
        apk = self.apk_var.get().strip()
        if not apk or not os.path.isfile(apk):
            messagebox.showwarning(APP_TITLE, "Selecciona un APK válido primero.")
            return

        def task() -> None:
            pkg, name = pipeline.load_apk_info(apk, self.log)
            self.after(0, lambda: self.pkg_var.set(pkg))
            self.after(0, lambda: self.name_var.set(name))
            self.log(f"Package actual: {pkg}")
            self.log(f"Nombre actual: {name}")

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
        if not new_name and not new_pkg:
            messagebox.showwarning(APP_TITLE, "Activa al menos un cambio.")
            return
        if new_pkg and not _valid_package(new_pkg):
            messagebox.showwarning(
                APP_TITLE,
                "El package name no es válido. Usa el formato com.empresa.app",
            )
            return

        def task() -> None:
            result = pipeline.process(apk, out, new_name, new_pkg, self.log)
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
