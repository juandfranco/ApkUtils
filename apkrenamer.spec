# PyInstaller spec - genera un único .exe sin consola.
# Uso: pyinstaller apkrenamer.spec

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=['src'],
    binaries=[],
    datas=[],
    hiddenimports=['apkrenamer', 'apkrenamer.gui', 'apkrenamer.pipeline',
                   'apkrenamer.renamer', 'apkrenamer.apk_tools'],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ApkRenamer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
