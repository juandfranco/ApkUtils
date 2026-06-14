# APK Renamer

App de escritorio para **Windows** sencilla para cambiar el **nombre visible**
y el **package name (application ID)** de un archivo `.apk`.

- Interfaz gráfica simple.
- Sin dependencias de Python que instalar: usa solo la librería estándar
  (Tkinter). Se distribuye como un **único `.exe`**.
- **Descarga TODO lo que necesita automáticamente** la primera vez: Java (un
  JRE portátil), `apktool` y el firmador. No hay que instalar nada a mano.

---

## Instalación (la forma fácil)

1. Descarga `ApkRenamer.exe`:
   - Pestaña **Actions** del repositorio → último build **Build Windows EXE** →
     sección **Artifacts** → `ApkRenamer-windows`.
   - (O compílalo tú mismo, ver más abajo.)
2. Ejecuta `ApkRenamer.exe`. No necesita instalación.

### Cero requisitos: todo es automático

La primera vez que procesas un APK (o pulsando **"Descargar Java + herramientas"**),
la app descarga sola y deja listos:

- **Java** (JRE Temurin 17 portátil) — solo si no tienes Java ya instalado.
- **apktool** — para decodificar y reconstruir el APK.
- **uber-apk-signer** — para alinear y firmar el APK.

Todo se guarda en `%LOCALAPPDATA%\ApkRenamer\tools`. Solo necesitas **conexión a
internet** la primera vez (la descarga ronda los 45 MB por el JRE).

---

## Uso

1. **APK de entrada**: elige el `.apk`.
2. **Cargar datos del APK**: lee el nombre y el package actuales.
3. Marca lo que quieras cambiar y escribe el nuevo **nombre visible** y/o el
   nuevo **package name** (formato `com.empresa.app`).
4. Elige la ruta del **APK de salida**.
5. **Procesar APK**. Al terminar tendrás un APK reconstruido y firmado, listo
   para instalar.

El APK resultante se firma con una clave **debug**, suficiente para instalarlo
en un dispositivo (no para publicarlo en Google Play).

---

## Cómo funciona el cambio de package name

Se cambia el atributo `package` del `AndroidManifest.xml` (el *application ID*
con el que Android identifica e instala la app). Antes de cambiarlo, los nombres
de componentes relativos (p. ej. `.MainActivity`) se expanden a su nombre
completo con el package original, de modo que siguen apuntando a las clases
reales. Así el renombrado es fiable y la app puede instalarse **junto a la
original** sin tocar el código compilado.

> Nota: algunas apps con providers/authorities fijos al package original pueden
> requerir ajustes adicionales. Para rebranding e instalación en paralelo, el
> cambio de application ID cubre la mayoría de los casos.

---

## Ejecutar desde el código fuente

Requiere Python 3.9+ (el instalador oficial de [python.org](https://www.python.org/)
ya incluye Tkinter):

```bat
run.bat
```

o:

```bash
python app.py
```

## Compilar el `.exe`

```bat
build.bat
```

El ejecutable queda en `dist\ApkRenamer.exe`. El repositorio también lo compila
automáticamente en cada push mediante GitHub Actions (`Build Windows EXE`).

---

## Estructura

```
app.py                      Punto de entrada
apkrenamer.spec             Configuración de PyInstaller (un solo .exe)
build.bat / run.bat         Compilar / ejecutar
src/apkrenamer/
  gui.py                    Interfaz Tkinter
  pipeline.py               Decodificar -> editar -> reconstruir -> firmar
  renamer.py                Edición de AndroidManifest y recursos
  apk_tools.py              Java + descarga de apktool y firmador
.github/workflows/          CI que compila el .exe en Windows
```
