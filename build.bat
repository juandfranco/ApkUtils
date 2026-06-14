@echo off
REM Compila ApkRenamer.exe (un solo archivo, sin consola).
REM Requiere Python 3.9+ instalado.

echo Instalando PyInstaller...
python -m pip install --upgrade pip
python -m pip install pyinstaller certifi

echo Compilando...
python -m PyInstaller --noconfirm apkrenamer.spec

echo.
echo Listo. El ejecutable esta en: dist\ApkRenamer.exe
pause
