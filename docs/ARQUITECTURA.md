# Arquitectura Técnica: Balisco

**Versión:** 2.0  
**Fecha:** Octubre 2026  
**Enfoque:** Híbrido Local-Cloud (Google Drive Desktop + Base de Datos Local Soberana)

---

## 1. Principio Fundamental de Diseño
Separación estricta de responsabilidades:
* **Google Drive (Cloud Storage):** Almacén remoto de terabytes de archivos pesados y generador de enlaces web inmutables (`drive_id`).
* **Balisco (Local Core):** Motor de base de datos (`biblioteca.db`), renderizador de interfaz gráfica, organizador de metadatos (etiquetas/categorías), sistema de notas integradas, motor de serendipia y gestor de portadas locales optimizadas.
* **Procesamiento 100% Local:** La base de datos vive y se procesa en el equipo del usuario; no hay dependencias de servidores externos ni APIs lentas con cuotas.

---

## 2. Diagrama de Capas

```
┌────────────────────────────────────────────────────────────────────────┐
│                       INTERFAZ DE USUARIO (GUI)                        │
│ - Ghost Input, Barra de Filtros Acumulativos (Swipe-to-Delete)         │
│ - Dock Superior de 6 Iconos SVG Puros con Animaciones de Morfismo Físico│
│ - Grid de Tarjetas con Degradados Funcionales y Botón Cíclico          │
│ - Vista Analítica de Etiquetas (Tags Hub ordenado por frecuencia)      │
│ - Panel Lateral Inspector (Hero Preview, Notas Markdown, Chips, Dock)   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────┐
│                            BALISCO CORE (Python)                       │
│  - Query Parser Acumulativo (Tokens dinámicos: +tag, -tag, @estado)    │
│  - Gestor de Apertura Dual (Local / Web + Self-Healing)                │
│  - Sincronizador Incremental con Filtro de Exclusión (.balisco_backup) │
│  - Motor de Serendipia (Aleatorio Puro y Contextual Ponderado)         │
│  - Gestor de Backup Directo a Drive (.balisco_backup/)                 │
│  - Gestor de Metadatos (Notas, Tags en lote, Estados, Favoritos)       │
│  - Gestor de Portadas & Purga (covers/{drive_id}.jpg)                  │
│  - Resolvedor Dinámico de Letra de Unidad (G:\, H:\)                   │
└─────────────────────┬──────────────────────────────┬───────────────────┘
                      │                              │
┌─────────────────────▼────┐   ┌─────────────────────▼───────────────────┐
│     LOCAL STORAGE        │   │             GOOGLE DRIVE                │
│ - biblioteca.db (UTF-8)  │   │ - Unidad Montada Stream (G:\, H:\)      │
│ - FTS5 Virtual Index     │   │ - Metadata SQLite local                 │
│ - portadas/ (30-80 KB/c) │   │ - .balisco_backup/ (Excluido de lectura)│
│ - Notas y Tags en vivo   │   │ - URLs Web Inmutables                   │
└──────────────────────────┘   └─────────────────────────────────────────┘
```

---

## 3. Modelo de Datos (`biblioteca.db`)

Base de datos SQLite en codificación **UTF-8 nativa**:

```sql
-- Tabla principal de elementos
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    drive_id TEXT UNIQUE,               -- Clave Cloud universal inmutable
    titulo TEXT NOT NULL,
    autor TEXT DEFAULT '',              -- Autor/es del material
    tipo TEXT NOT NULL,                 -- 'pdf' (libro) o 'curso' (carpeta indivisible) o 'video'
    categoria_macro TEXT DEFAULT 'General',
    subcategoria TEXT DEFAULT '',
    etiquetas TEXT DEFAULT '',          -- '+historia +dk +anatomia +lauricella'
    descripcion TEXT DEFAULT '',
    notas TEXT DEFAULT '',              -- Notas personales en Markdown
    estado_lectura TEXT DEFAULT 'pendiente', -- 'pendiente', 'leyendo', 'leido', 'abandonado'
    rating INTEGER DEFAULT 0,           -- Calificación de 0 a 5 estrellas
    es_favorito INTEGER DEFAULT 0,      -- 1 = Destacado, 0 = Normal
    ruta_relativa TEXT NOT NULL,        -- 'Mi unidad\Biblioteca\Cultura\...'
    ruta_portada TEXT,                  -- 'portadas/{drive_id}.jpg'
    tamano_bytes INTEGER DEFAULT 0,
    mime_type TEXT,
    fecha_agregado TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ultimo_acceso TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_items_busqueda 
ON items(categoria_macro, subcategoria, estado_lectura, rating, es_favorito);

-- Tabla de configuración del sistema (Tema, preferencias de zoom, atajos)
CREATE TABLE IF NOT EXISTS configuracion (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);

-- Motor de Búsqueda de Alto Rendimiento FTS5 (Búsqueda global unificada < 2ms: Título, Autor y Notas)
CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
    titulo, 
    autor,
    etiquetas, 
    notas,
    categoria_macro, 
    subcategoria, 
    content='items', 
    content_rowid='id'
);
```

---

## 4. Motor de Búsqueda Acumulativo ("Ghost Input" y Filtros Vivos)

### A. Búsqueda progresiva (Ghost Input)
* La lupa, `Ctrl+F`, `/` o la primera tecla alfanumérica abren el campo de búsqueda. El campo no ocupa espacio cuando está cerrado.
* El texto ordinario consulta el índice FTS mientras se escribe, con coincidencia por prefijo de palabra. `Enter` fija el término como píldora; `Esc` cierra el campo y restaura los filtros fijados.
* Los operadores `+`, `-` y `@` se aplican al confirmar con `Enter`. Retroceso con el campo vacío elimina la última píldora.
* `+` y `-` muestran sugerencias de etiquetas del perfil activo antes de confirmar el filtro. `@favoritos` filtra por `items.es_favorito=1`; los cuatro estados siguen usando `items.estado_lectura`.
* Varios autores se guardan en `items.autor` separados por saltos de línea. Los registros anteriores con un solo valor siguen siendo válidos y el índice FTS5 conserva la búsqueda por cualquiera de los nombres. La sincronización y la limpieza de títulos preservan los autores ya editados.

### B. Comportamiento Estrictamente Acumulativo
Los filtros **nunca se reinician al escribir un nuevo término; se van sumando en cadena**:
1. Tecleas `+historia` ➔ Se fija la píldora verde `[ historia ✕ ]`. El catálogo se filtra a Historia.
2. Luego tecleas `-novela` ➔ Se suma la píldora roja `[ novela ✕ ]`. El catálogo excluye novelas.
3. Luego tecleas `roma` ➔ Se suma la píldora gris `[ "roma" ✕ ]`. El catálogo busca "roma" en el título.
4. Luego tecleas `@pendiente` ➔ Se suma el filtro de estado. El resultado final cumple **todos los filtros a la vez**.

### C. Gesto "Swipe to Delete" (Barrido con Mouse)
* Para eliminar un filtro individual: Clic en su `✕`.
* Para eliminar múltiples filtros rápido: **Mantener presionado el clic sobre una píldora y arrastrar el cursor horizontalmente sobre las demás sin soltar el clic**. Las píldoras se desvanecen en cadena.
* Tecla `Escape`: Restablece todo el catálogo a cero.

---

## 5. Detección y Comportamiento de Entidades (Grid Unificado)

### A. Libros y Documentos (`tipo = 'pdf'`)
* Archivos individuales `.pdf` o `.epub`.
* **Colecciones y Volúmenes (Caso Lauricella 1-12):** Cada tomo es un ítem individual con lectura directa en 1 clic, conectados visualmente por etiquetas (`+lauricella +morfologia`).
* **Apertura:** Ejecuta directamente el visor nativo de Windows (`os.startfile(ruta_pdf)`).

### B. Carpetas Complejas y Cursos (`tipo = 'curso'`)
* Carpetas que contienen material de estudio compuesto (ej. `Curso Blender 3D` con archivos `.blend`, texturas, videos `.mp4` y subcarpetas).
* **Tarjeta en Grid:** Idéntica a la de un libro, con soporte de portada personalizada (`portadas/{drive_id}.jpg`) y badge `CURSO`.
* **Freno de Escaneo:** Balisco no indexa los archivos internos en la base principal para evitar saturación de datos y descargas accidentales en masa.
* **Apertura (Lanzador Integrado):**
  * Al hacer clic, abre una vista interna en **modo lista** (sin miniaturas pesadas) con los archivos y videos del curso.
  * Cada archivo tiene botón para reproducir o abrir en su app correspondiente (VLC, Blender, etc.).
  * Incluye acceso directo: `[ 📁 Abrir carpeta en Windows ]` para saltar a Windows Explorer.

---

## 6. Reglas Estrictas de Exclusión en el Escaneo (Blindaje de `.balisco_backup`)

Para evitar que la carpeta de copias de seguridad contamine la biblioteca:
* **Filtro de Raíz de Sincronización:** Durante la lectura de `metadata_sqlite_db` de DriveFS, el escáner aplica un filtro estricto:
  ```python
  # Ignora cualquier carpeta o archivo que empiece con punto o contenga 'backup'
  if item_title.startswith(".") or "balisco_backup" in ruta_relativa:
      continue  # NO se registra en items ni se procesa
  ```
* **Garantía:** `G:\Mi unidad\Biblioteca\.balisco_backup\` permanece 100% invisible para el catálogo de libros y cursos.

---

## 7. Módulo de Serendipia y Animaciones de Morfismo Físico

### A. Animación de Morfismo: Del Dado a la Diana ("Hold & Swipe Right")
* **En reposo:** Un botón con un dado cúbico geométrico isométrico SVG de trazo fino (`stroke-width="1.6"`).
* **Al hacer Clic Rápido (Tap):** El dado gira sobre su propio eje 360° con física de resorte (`spring physics`), selecciona un elemento puramente aleatorio y lo abre/destaca.
* **Al Mantener Presionado y Deslizar a la Derecha (Hold & Drag Right):**
  1. **Fase 1 (0px a 30px):** El botón se estira horizontalmente como una píldora elástica. El dado comienza a girar rápidamente sobre sí mismo.
  2. **Fase 2 (30px a 60px):** Las caras del dado se aplanan y sus aristas se curvan en una transición fluida de vectores (SVG Path Morphing), convirtiéndose en los círculos concéntricos de una **Diana / Radar de Intereses (`🎯`)**.
  3. **Fase 3 (Glow & Feedback):** La cápsula adquiere un suave halo de luz ámbar/azul y muestra una micro-etiqueta: *"Intereses Recientes"*.
  4. **Al soltar el clic:** Se ejecuta la consulta semi-aleatoria contextual ponderada (analizando los últimos temas abiertos).

---

## 8. Especificación Técnica de Módulos y Funciones (API Interna)

### Módulo: `core/search_parser.py` (Motor de Búsqueda Acumulativo)
* `agregar_filtro(token: str, estado_actual_filtros: dict) -> dict`:
  * Clasifica el token en `tags_incluir` (`+`), `tags_excluir` (`-`), `estados` (`@`) o `texto_libre` (busca unificadamente en Título, Autor y Notas).
* `remover_filtro(id_pildora: str, estado_actual_filtros: dict) -> dict`:
  * Elimina una píldora y re-ejecuta la consulta.
* `construir_query_sql(filtros_activos: dict) -> tuple[str, list]`:
  * Genera la consulta SQL/FTS5 acumulativa en < 1 ms buscando coincidencias en Título, Autor o Notas cuando hay texto libre.
* `limpiar_todos_filtros() -> dict`:
  * Restaura el catálogo completo.

### Módulo: `core/drive_sync.py` (Sincronizador Seguro con Exclusiones y Multicuenta)
* `detectar_perfiles_drive() -> list[dict]`:
  * Inspecciona `AppData\Local\Google\DriveFS` y retorna la lista de cuentas/perfiles activos con su ID y si contienen carpeta `Biblioteca`.
* `obtener_o_seleccionar_perfil_activo(conexion_db) -> str`:
  * Si hay 1 solo perfil con biblioteca, lo usa automáticamente. Si hay 2 cuentas y ambas tienen biblioteca, lee la clave `id_perfil_drive` de `configuracion`. Si es la primera vez, solicita al usuario elegir en un modal minimalista y guarda su elección de por vida (conmutable en cualquier momento).
* `cambiar_perfil_activo(nuevo_id_perfil: str, conexion_db) -> bool`:
  * Permite rectificar o cambiar de cuenta en caso de haber elegido la equivocada, reconfigurando la fuente de sincronización sin perder datos.
* `obtener_letra_drive() -> str`:
  * Detecta dinámicamente la letra donde está montada `Mi unidad\Biblioteca`.
* `conectar_db_drive_ro(ruta_db: str) -> sqlite3.Connection`:
  * Abre conexión segura `file:...mode=ro` con timeout 10s.
* `reconstruir_ruta_desde_parents(stable_id: int, cursor) -> str`:
  * Reconstruye el árbol de carpetas ignorando nodos ocultos o `.balisco_backup`.
* `sincronizar_biblioteca(ruta_raiz: str = "Biblioteca") -> dict`:
  * Extrae elementos nuevos, actualiza rutas y purga `trashed = 1`.

### Módulo: `core/tags_manager.py` (Hub Analítico de Etiquetas)
* `obtener_etiquetas_ordenadas_frecuencia(conexion_db) -> list[dict]`:
  * Retorna todas las etiquetas del catálogo con su recuento numérico de mayor a menor (`[{"tag": "anatomia", "total": 48}, ...]`).
* `actualizar_etiquetas_item(drive_id: str, nuevas_etiquetas: str) -> bool`:
  * Actualiza tags y sincroniza el índice FTS5.
* `asignar_etiquetas_en_lote(lista_drive_ids: list[str], etiqueta: str, accion: str = "agregar") -> int`:
  * Añade o quita una etiqueta a múltiples tarjetas simultáneamente.

### Módulo: `core/serendipity.py` (Motor de Descubrimiento)
* `obtener_aleatorio_puro(conexion_db) -> dict`:
  * Ejecuta `SELECT * FROM items ORDER BY RANDOM() LIMIT 1`.
* `obtener_semi_aleatorio_contextual(conexion_db, limite_historial: int = 8) -> dict`:
  * Analiza los últimos elementos con `ultimo_acceso`, extrae sus etiquetas más repetidas y busca un elemento no leído (`estado_lectura != 'leido'`) que comparta esas etiquetas.

### Módulo: `core/backup_manager.py` (Respaldo Cloud en Drive)
* `crear_backup_en_drive(ruta_letra_drive: str) -> str`:
  * Empaqueta `biblioteca.db` + `portadas/` en un archivo `Balisco_Backup_YYYY-MM-DD.zip`.
  * Lo deposita en `G:\Mi unidad\Biblioteca\.balisco_backup\`. Retorna la ruta del archivo generado.

### Módulo: `core/items_manager.py` (Gestor de Elementos y Lanzador)
* `abrir_item(drive_id: str, modo: str = "local") -> bool`:
  * Abre con `os.startfile` o `webbrowser.open`. Auto-repara rutas renombradas y actualiza `ultimo_acceso`.
* `auto_reparar_ruta(drive_id: str) -> str`:
  * Sincroniza nueva ruta en caso de que el archivo haya sido movido en Drive.
* `cambiar_titulo(drive_id: str, nuevo_titulo: str) -> bool`:
  * Permite renombrar el título visible en Balisco marcando `titulo_personalizado=1`.
* `cambiar_autor(drive_id: str, nuevo_autor: str) -> bool`:
  * Actualiza el autor del material y sincroniza con el índice FTS5.
* `actualizar_notas(drive_id: str, texto_notas: str) -> bool`:
  * Auto-guardado en Markdown y sincronización FTS5.
* `cambiar_estado_lectura(drive_id: str, nuevo_estado: str) -> bool`:
  * Conmuta estado (`pendiente`, `leyendo`, `leido`, `abandonado`).
* `cambiar_rating(drive_id: str, nuevo_rating: int) -> bool`:
  * Actualiza la calificación de 0 a 5 estrellas para el elemento.
* `eliminar_item(drive_id: str) -> bool`:
  * Traslada a la papelera con `send2trash` y elimina registro local.
