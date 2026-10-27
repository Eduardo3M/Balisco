<p align="center">
  <img src="ui/banner.png" alt="Balisco" width="100%" />
</p>

<h1 align="center">Balisco v1.0</h1>

<p align="center">
  <strong>Tu biblioteca visual inteligente sobre Google Drive con reproductor y lector multiformato integrado, sin ocupar espacio en tu PC.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-1.0.0-blue.svg?style=flat-square" alt="Versión 1.0.0" />
  <img src="https://img.shields.io/badge/platform-Windows%20x64-informational.svg?style=flat-square" alt="Plataforma Windows x64" />
  <img src="https://img.shields.io/badge/python-3.12%2B-brightgreen.svg?style=flat-square" alt="Python 3.12+" />
  <img src="https://img.shields.io/badge/storage-Google%20DriveFS-orange.svg?style=flat-square" alt="Google Drive" />
</p>

---

**Balisco** es una aplicación de escritorio de alto rendimiento para Windows que convierte tu unidad de **Google Drive para escritorio** en un centro multimedia y biblioteca visual para tus libros, documentos, cursos y colecciones, permitiendo leer, visualizar y reproducir contenidos al instante sin necesidad de sincronizarlos ni descargarlos a tu disco duro.

## ✨ Características Principales

- **Explorar sin descargar:** Visualiza tu catálogo completo con portadas en alta resolución, autores, formatos y estados de lectura leyendo directamente los metadatos de Google DriveFS.
- **Reproductor y Lector Integrado Multiformato (Modo Balisco):**
  - **PDF y Cómics (CBZ):** Renderizado vectorial ultranítido de páginas, capa de selección de texto, índice de contenidos interactivo, búsqueda textual interna y sistema de marcadores personales.
  - **Lectura a Doble Página:** Vista de pliego a dos páginas lado a lado con zoom proporcional inteligente, adaptación de ancho completo y ajuste de página completa (`fitPage`) sin cortes verticales ni franjas negras.
  - **Temas de Lectura Unificados:** Filtros visuales accesibles con iconos intuitivos (Modo Original/Claro, Sepia y Noche/Oscuro) en PDF, EPUB y documentos de texto.
  - **Libros Electrónicos (EPUB):** Ajuste fino de tamaño de fuente, vista de una o dos columnas, navegación por capítulos e índice de contenidos.
  - **Código y Texto Plano (TXT, MD):** Visualización limpia con fuentes monoespaciadas legibles y control dinámico de tamaño.
  - **Vídeo y Audio (MP4, MP3, etc.):** Reproductor fluido con vista previa en miniatura al deslizar la barra de tiempo (*scrubbing*), marcas de tiempo, velocidad de reproducción y modo PiP (Picture in Picture).
  - **Pantalla Dividida (Split View):** Visualiza o compara dos documentos/contenidos en paralelo de forma simultánea con galería lateral de navegación rápida.
- **Organización Automática y Taxonomía Inteligente:**
  - La primera etiqueta de cada elemento define su carpeta real en Google Drive (con carpeta `_Inbox` para archivos pendientes de clasificar).
  - Etiquetas múltiples para catalogar un mismo archivo en diversos ámbitos de interés.
  - Clasificación por idioma de lectura, estrellas de calificación y estados de lectura (*Pendiente, Interesado, Leyendo, Leído, Abandonado*).
- **Gestión por Lotes y Edición Contextual:** Modificación masiva de títulos, asignación de idiomas, etiquetas y estados con soporte directo de la tecla `F2`.
- **Contenedores y Cursos:** Agrupación de colecciones con múltiples recursos o subcarpetas, navegación mediante migas de pan (*breadcrumbs*) y seguimiento individual de cada recurso.
- **Búsqueda Potente Bilingüe:** Filtro instantáneo por texto o mediante tokens especializados con sugerencias compactas: `+etiqueta`, `@autor:`, `@estado:` (o `@status:`), `@idioma:` (o `@lang:`), `@formato:`, `@orden:`, `@favoritos`, etc.
- **Generación y Edición de Portadas:** Recorte y encuadre interactivo de portadas personalizadas, soporte de generación automática local y ejecución en lote mediante Google Colab.
- **Perfiles Independientes por Cuenta y Respaldos:** Aislamiento total de configuraciones, bases de datos y portadas por cada cuenta de Google Drive (`%LOCALAPPDATA%\Balisco\perfiles\<id>\`) con copias de seguridad automáticas comprimidas en Drive.
- **Interfaz Bilingüe:** Cambio instantáneo entre Español e Inglés desde el dock principal.

## 🚀 Instalación (Windows x64)

1. Instala y mantén en ejecución **Google Drive para escritorio**.
2. Descarga e instala **`BaliscoSetup-1.0.0-win-x64.exe`** desde la sección de [**Releases**](https://github.com/Eduardo3M/Balisco/releases/latest).
3. Al abrir Balisco, selecciona o crea la carpeta de tu biblioteca dentro de `Mi unidad`.

> Tus notas, etiquetas, portadas y configuraciones se guardan de forma segura fuera del directorio de instalación en `%LOCALAPPDATA%\Balisco`, por lo que actualizar o reinstalar la aplicación nunca altera tus datos ni tus archivos de Drive.

## 🛠️ Desarrollo y Compilación

Requiere **Windows x64** y **Python 3.12+**.

```powershell
# Instalar dependencias del proyecto
python -m pip install -e ".[build]"

# Ejecutar en entorno local
python Balisco.pyw

# Generar el instalador ejecutable para Windows x64 (requiere Inno Setup 6)
python scripts/build_installer.py
```
