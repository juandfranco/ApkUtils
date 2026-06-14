"""Punto de entrada para ejecutar la app y para empaquetar con PyInstaller."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from apkrenamer.gui import main  # noqa: E402

if __name__ == "__main__":
    main()
