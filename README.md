<p align="center">
  <img src="ui/banner.png" alt="Balisco" width="100%" />
</p>

<h1 align="center">Balisco</h1>

<p align="center">
  <strong>Tu biblioteca visual sobre Google Drive, sin ocupar espacio en tu PC.</strong>
</p>

---

**Balisco** es una aplicación de escritorio para Windows que convierte una carpeta de **Google Drive para escritorio** en una biblioteca visual para tus libros, documentos, cursos y colecciones, sin necesidad de descargar todos los archivos a tu disco duro.

## ✨ Qué puedes hacer

- **Explorar sin descargar:** Visualiza tu catálogo con portadas, autor, formato y progreso leyendo directamente los metadatos de Google Drive.
- **Organización automática por etiquetas:** La primera etiqueta de cada elemento define su carpeta en Drive (y `_Inbox` guarda lo que aún no clasificas). Las demás etiquetas sirven para filtrarlo desde varios temas.
- **Contenedores y cursos:** Agrupa carpetas con múltiples archivos o subcarpetas y haz seguimiento individual de tus recursos favoritos, calificados o en progreso.
- **Búsqueda rápida y filtros:** Filtra al instante por texto, etiquetas (`+tema`), autor (`@autor`), favoritos (`@favoritos`), estado de lectura o calificación.
- **Portadas locales o con Google Colab:** Genera portadas directamente en tu equipo o en lote desde Google Colab para no descargar archivos pesados.
- **Multicuenta y respaldos:** Cada cuenta de Google Drive mantiene su propio perfil local aislado (`%LOCALAPPDATA%\Balisco\perfiles\<id>\`) y puedes guardar copias de seguridad en tu Drive con un clic.

## 🚀 Instalación (Windows x64)

1. Instala y mantén abierto **Google Drive para escritorio**.
2. Descarga e instala **`BaliscoSetup-0.1.9-win-x64.exe`** desde la sección de [**Releases**](https://github.com/Eduardo3M/Balisco/releases/latest).
3. Al abrir Balisco, elige o crea la carpeta de tu biblioteca dentro de `Mi unidad`.

> Tus notas, etiquetas, portadas y preferencias se guardan fuera de la instalación en `%LOCALAPPDATA%\Balisco`, por lo que actualizar o desinstalar la app nunca borra tus datos ni tus archivos de Drive.

## 🛠️ Desarrollo y compilación

Requiere **Windows x64** y **Python 3.12+**.

```powershell
# Instalar dependencias
python -m pip install -e ".[build]"

# Ejecutar desde código fuente
python Balisco.pyw

# Generar el instalador Windows x64 (requiere Inno Setup 6)
python scripts/build_installer.py
```
