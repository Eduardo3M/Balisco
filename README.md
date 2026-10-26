# Balisco — Biblioteca y Archivo de Conocimiento Personal

Balisco es una aplicación de escritorio de alto rendimiento diseñada para indexar, explorar y gestionar libros, contenedores y documentos alojados en Google Drive, con cero descargas obligatorias de binarios pesados y una interfaz moderna acelerada por GPU a 144 FPS.

---

## Características Principales

* **Indexación Instantánea sin descargas (0 MB):** Lee metadatos directamente de la base local de Google DriveFS (`metadata_sqlite_db`) y usa el `drive_id` de cada archivo.
* **Recuperación de metadatos de PDF:** Si un PDF vuelve con otro ID en la misma ruta del mismo perfil, Balisco conserva su ficha, notas, etiquetas y portada cuando existe una sola correspondencia posible. Si hay varios candidatos, mantiene las fichas separadas para evitar asociaciones erróneas. Una nueva versión con el mismo ID conserva la ficha normalmente.
* **Contenedores:** Cada carpeta inmediata de `Biblioteca/Containers/` ocupa una sola tarjeta. Sus archivos se muestran como recursos al abrirla. La búsqueda profunda está apagada por defecto; al activarla, sus títulos internos se buscan globalmente a través de la tarjeta del contenedor.
* **Limpieza Estética Automática:** Elimina extensiones (`.pdf`, `.epub`), hashes MD5, identificadores web (`Anna's Archive`, `libgen`, `z-lib`) y extrae automáticamente los autores a los metadatos.
* **Búsqueda FTS5 en Tiempo Real:** Búsqueda instantánea con filtros acumulativos (`+etiqueta`, `-excluir`, `@estado`, `@tipo:pdf/contenedor/video`, `@rating:1-5`).
* **Serendipia Táctil (Dado / Diana):**
  * **Rueda del ratón / Clic derecho:** Alterna fluidamente entre modo *Aleatorio puro* 🎲 y modo *Intereses recientes* 🎯.
  * **Clic izquierdo:** Lanza la tirada y localiza de inmediato una pieza de conocimiento.
* **Ajuste de Cuadrícula con Rueda:** Gira la rueda del ratón sobre el botón de cuadrícula para ajustar el tamaño de las tarjetas en tiempo real.
* **Inspector Lateral Completo:** Portadas de alta definición (con soporte de arrastrar y soltar), edición de notas Markdown con persistencia continua, calificación por estrellas, etiquetas y enlace directo a Google Drive. La edición masiva permite cambiar autores y etiquetas de varios libros.
* **Persistencia de Geometría:** Recuerda posición, dimensiones y estado maximizado de la ventana entre sesiones.

---

## Ejecución y Desarrollo

El punto de entrada principal es `Balisco.pyw` (ejecutable sin consola en Windows):

```powershell
# Ejecución directa
python Balisco.pyw

# Opciones por línea de comandos
python Balisco.pyw --perfiles
python Balisco.pyw --sincronizar
python Balisco.pyw --buscar +ciencias @pendiente
```

### Ubicación de Datos
Los datos de la aplicación se almacenan de forma segura fuera del árbol sincronizado:
* Base de datos SQLite: `%LOCALAPPDATA%\Balisco\biblioteca.db`
* Portadas en alta definición: `%LOCALAPPDATA%\Balisco\portadas\{drive_id}.jpg`
* Almacén WebView2: `%LOCALAPPDATA%\Balisco\webview\`

### Generar instalador Windows

Requisitos de compilación: Windows x64, Python 3.12+, Inno Setup 6.3+ y las dependencias:

```powershell
python -m pip install -e ".[build]"
python scripts/build_installer.py
```

El script detecta `ISCC.exe` instalado (también admite `--iscc RUTA` o la variable `ISCC`), limpia `build/` y `dist/`, compila con PyInstaller e Inno Setup y elimina los intermedios tras terminar. El resultado es `dist/BaliscoSetup.exe`. Si la compilación falla conserva los intermedios para diagnóstico.

El instalador instala por usuario en `%LOCALAPPDATA%\Programs\Balisco`, crea accesos en Escritorio y Menú Inicio con AppUserModelID y registra el desinstalador. La biblioteca y portadas de `%LOCALAPPDATA%\Balisco` se conservan al actualizar o desinstalar. El equipo de destino necesita Microsoft Edge WebView2 Runtime y .NET Framework 4.8 (habituales en Windows 10/11); Python va incluido.

Instalación desatendida:

```powershell
.\dist\BaliscoSetup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-
```

Validación: `python -m unittest discover -s tests -v` y `python tests/window_smoke.py`. La segunda abre una ventana temporal y comprueba cambios nativos de maximizado/restaurado, guardado de geometría y conservación de la última edición al cerrar.

---

## Arquitectura del Proyecto

```
Balisco/
├── Balisco.pyw          # Launcher y puente de escritorio WebView2
├── pyproject.toml       # Dependencias y configuración de empaquetado
├── core/                # Módulos del núcleo Python
│   ├── database.py      # Esquema SQLite, WAL, índices y triggers FTS5
│   ├── drive_sync.py    # Lógica de sincronización DriveFS y contenedores
│   ├── cleaner.py       # Limpieza estética de títulos y extracción de autores
│   ├── search_parser.py # Motor de filtros y consulta FTS5
│   ├── desktop_api.py   # Puente de llamadas JS <-> Python
│   ├── serendipity.py   # Algoritmos de selección aleatoria y contextual
│   ├── tags_manager.py  # Gestión analítica de etiquetas
│   ├── backup_manager.py# Respaldos automatizados
│   └── shortcut_helper.py# Gestión de accesos directos de Windows
├── ui/                  # Interfaz acelerada por GPU (HTML5 / Vanilla CSS / JS)
│   ├── index.html       # Estructura semántica
│   ├── styles.css       # Sistema de diseño carbón/zinc
│   ├── app.js           # Controladores de UI, render virtual y eventos
│   └── icons.js         # Iconografía vectorial SVG nativa
└── docs/                # Documentación de arquitectura y diseño
    ├── ARQUITECTURA.md  # Especificaciones técnicas del núcleo
    ├── DISENO.md        # Guía del sistema de diseño visual
    └── FUNCIONES_FUTURAS_BALISCO.md # Hoja de ruta para futuras versiones
```
