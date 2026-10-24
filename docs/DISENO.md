# Sistema de Diseño y Especificación Visual: Balisco

**Versión:** 3.5  
**Inspiración Visual:** Eagle App Desktop / macOS Pro Aesthetics  
**Filosofía Central:** Cero menús textuales aburridos. Cero cajas de búsqueda tradicionales (Ghost Search). Cero conceptos de "Folders/Carpetas" en la interfaz (se reemplaza por metadatos planos). Puros botones de control físico con iconografía vectorial SVG, filtros acumulativos en píldoras visuales interactivas, filtrado por Rating desplegable fluido y Embudo por Tipo de Entidad.

---

## 1. Barra Superior Minimalista (Pure Icon Dock & Active Filters Bar)

La barra superior (54px de alto) se divide en dos zonas maestras:

```
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│  [ZONA IZQUIERDA: PÍLDORAS DE FILTROS ACTIVOS]   │  [ZONA DERECHA: MUELLE DE ICONOS EXPANDIDO] │
│  [🔎] [+historia ✕] [-venganza ✕]              │  [🏷️] [🎲] [♥] [✓] [⭐] [🌪️] [🎛️] [🌓]   │
└────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### A. Zona Derecha: Muelle de Iconos Puros (Agrupados por Función)

De izquierda a derecha, cada función vive en un único botón circular o cuadrado redondeado SVG (sin texto visible):

1. **Botón Explorador de Etiquetas (`🏷️` Tags Hub):**
   * Abre la vista analítica de etiquetas (ordenadas de mayor a menor frecuencia con su contador numérico).
   * La cuadrícula deja 24 px de espacio bajo la barra superior para que la primera fila respire igual que el resto de la vista.
2. **Botón Gestual de Serendipia (`🎲` Dado / Hold & Swipe):**
   * *Clic simple:* Dispara **Aleatorio Puro** con rotación 360° en física de resorte.
   * *Dejar presionado y arrastrar a la derecha:* Morfismo SVG fluido a diana `🎯` y dispara **Semi-Aleatorio Contextual** (por intereses recientes).
3. **Botón de Calificación Desplegable (`⭐` Rating Filter):**
   * *En reposo:* Icono SVG de una estrella limpia.
   * *Al hacer clic:* Se despliega fluidamente hacia la derecha una cápsula horizontal con **5 estrellas interactivas** (`★ ★ ★ ★ ★`).
   * *Interacción fluida:* Al pasar el cursor por encima, las estrellas se iluminan en dorado en tiempo real. Al hacer clic (ej. en la 4ª estrella), se confirma el filtro de "4 estrellas o más" y agrega la píldora correspondiente a la barra de filtros izquierda.
4. **Botón Embudo por Tipo de Entidad (`🌪️` Funnel Filter):**
   * Filtra exclusivamente **entidades de primer nivel** (libros, cursos, videos maestros), nunca archivos internos.
   * *Menú desplegable de iconos en píldora:*
     * `[ 📄 Documentos / Libros ]` (PDF/EPUB)
     * `[ 🎓 Cursos / Paquetes ]` (Carpetas indivisibles)
     * `[ 🎬 Videos / Estudio ]` (Piezas audiovisuales)
5. **Botón de Modos de Cuadrícula / Zoom (`🎛️` Grid Control):**
   * *Clic cíclico:* Conmuta entre tamaños predeterminados: **Grid Pequeño** (muchas miniaturas) ➔ **Grid Mediano** ➔ **Grid Grande** (modo póster).
   * *Gesto Hold & Drag:* Al igual que el dado, si mantienes el clic presionado sobre el icono del grid y **arrastras el mouse hacia la derecha o izquierda**, el tamaño de las tarjetas se acerca o aleja de forma continua y suave (Zoom fluido a 144 Hz).
6. **Botón Conmutador Dual Local / Web (`📁 / 🌐` Toggle Dual):**
   * Alterna el modo de apertura por defecto al hacer clic en las tarjetas (Modo Local con app nativa vs Modo Web en Google Drive).
7. **Botón de Copia de Seguridad Instantánea (`💾` Cloud Backup):**
   * Un clic genera el archivo `.zip` con la base de datos y portadas y lo deposita directamente en `G:\Mi unidad\Biblioteca\.balisco_backup\` para sincronización automática en la nube de Drive.
8. **Botón de Tema Cíclico (`🌓` Theme Loop):**
   * Alterna con un toque entre `Auto (Sistema Windows)` ➔ `Dark` ➔ `Light`.

---

### B. Zona Izquierda: Barra Dinámica de Filtros ("Live Chips Bar")

La lupa de la barra superior abre un campo de búsqueda. También se puede abrir con `Ctrl+F`, `/` o al empezar a escribir fuera de otro campo. Los resultados se actualizan mientras se escribe, aceptan prefijos de palabras y no distinguen entre letras con o sin tilde (`analisi` encuentra «Análisis»). La búsqueda reutiliza las tarjetas visibles y espera solo 70 ms tras la última tecla antes de consultar el índice. `Enter` fija el término como filtro y cierra el campo; `Esc` cierra una búsqueda en curso sin borrar los filtros. Si no hay una búsqueda en curso, `Esc` limpia todos los filtros. Con el campo vacío, Retroceso elimina el último filtro.
Al escribir `+` o `-` aparece una barra con etiquetas existentes de la cuenta activa, ordenadas por frecuencia. El usuario puede seguir escribiendo, elegir una sugerencia con clic o recorrerlas con las flechas y confirmar con `Enter`. La coincidencia de sugerencias ignora tildes; las etiquetas se consultan una vez y la lista se actualiza después de editar etiquetas o sincronizar.
Los términos fijados aparecen como **píldoras (chips) visuales con código de color de contorno**:

* 🟢 **Contorno Verde Esmeralda (`+etiqueta`):** Filtro de inclusión obligatoria (ej. `[ historia ✕ ]`).
* 🔴 **Contorno Rojo Carmín (`-etiqueta`):** Filtro de exclusión estricta (ej. `[ novela ✕ ]`).
* ⚪ **Contorno Gris Zinc / Neutro (Búsqueda en título, autores y notas):** Búsqueda directa (ej. `[ "robotica" ✕ ]`).
* 🟡 **Contorno Dorado (`@rating` o `@estado`):** Filtro de estrellas o lectura (ej. `[ ★★★★☆ ✕ ]`).

#### Gesto de Eliminación Fluida ("Swipe-to-Delete"):
* **Eliminar una píldora:** Clic individual en su botón `✕`.
* **Gesto "Swipe to Clear" (Barrido continuo):**
  * Mantener presionado el clic sobre una píldora y arrastrar el mouse sobre las contiguas sin soltar para borrarlas en cadena como una cuchilla.
* **Tecla Escape (`Esc`):** Cierra primero la búsqueda en curso; al pulsarla fuera del campo, limpia todos los filtros y restaura la vista completa del catálogo.

---

## 2. Nueva Vista Especial: Hub de Etiquetas (Tags Analytical View)

Al presionar el **Botón de Etiquetas (`🏷️`)** en la barra superior:
* Lista analítica limpia ordenada **estrictamente de mayor a menor frecuencia** (ej. `#anatomia: 48 libros`, `#lauricella: 12 volúmenes`).
* Un clic en cualquier etiqueta vuelve al Grid con esa etiqueta aplicada en una píldora verde.

---

## 3. Anatomía de la Tarjeta del Grid: La Franja con Degradado Funcional

```
┌──────────────────────────────────────────────┐
│ [PDF]                     [◯ Botón Cíclico]  │
│                                              │
│               PORTADA DEL LIBRO              │
│               (Alta Definición)              │
│                                              │
├──────────────────────────────────────────────┤
│ ░░░░░░░░░ DEGRADADO DE ESTADO ░░░░░░░░░░░░░ │  <-- Barra con glow
├──────────────────────────────────────────────┤
│ Título del Libro o Curso                     │
│ ★★★★★  • 145 MB • #anatomia                  │
└──────────────────────────────────────────────┘
```

### La Franja con Degradado en la Base de la Portada:
* 🟢 **Degradado Esmeralda (`@leido`):** `rgba(16, 185, 129, 0.9)` con resplandor suave.
* 🟡 **Degradado Ámbar (`@leyendo`):** `rgba(245, 158, 11, 0.9)` con resplandor dorado.
* ⚪ **Degradado Gris Zinc (`@pendiente`):** `rgba(107, 114, 128, 0.4)`.
* 🔴 **Degradado Carmín (`@abandonado`):** `rgba(239, 68, 68, 0.8)`.

### Botón Cíclico Superior en la Tarjeta:
* Conmuta con 1 clic: `⚪ Pendiente` ➔ `🟡 Leyendo` ➔ `🟢 Leído` ➔ `🔴 Abandonado`.

---

## 4. Panel Lateral Derecho: Inspector y Previsualización (Fiel a la Referencia)

El panel lateral derecho se mantiene limpio, vertical y sin sobrecargas, idéntico a la referencia visual:

* **Hero Preview:** Muestra la portada con badge de formato (`PDF`, `CURSO`, etc.). Un doble clic izquierdo abre el archivo; un clic derecho permite elegir una imagen JPG/PNG para añadir o reemplazar la portada. Soltar una imagen sobre la portada también funciona, sin mostrar un texto de arrastre permanente.
* **Título Editable en Línea:** Campo de texto limpio para editar el nombre visible.
* **Caja de Notas Rápidas:** Campo para apuntes con auto-guardado en 500 ms (indexado en FTS5).
* **Fila de Enlace a Google Drive con Botón Directo:**
  * Input estilizado que muestra la URL de Google Drive.
  * **Botón de Enlace Directo (SVG `external-link`):** Al hacer clic, **te abre directamente el archivo en Google Drive en tu navegador web** (en lugar de solo copiar el enlace).
* **Gestor de Tags (Píldoras con `+`):** Píldoras interactivas con botón `+` para añadir nuevas etiquetas.
* **Autores:** Justo debajo de las etiquetas, cada autor aparece en una ficha con una acción para quitarlo y un botón `+` para añadir otro. Los nombres se conservan en la base de datos y se indexan en FTS5 para búsquedas globales. Un valor antiguo de autor permanece como una sola ficha hasta que el usuario lo edite.
* **Ficha de Propiedades / Metadatos (Properties):**
  * **Favorito:** Corazón para marcar o desmarcar el libro en la base de datos. Los libros favoritos muestran un corazón pequeño en la tarjeta.
  * **Rating con 5 Estrellas Interactivas:** Selector de 1 a 5 estrellas (`★★★★★`) interactivo directamente en el panel.
  * **Dimensiones / Páginas:** Metadata física del documento.
  * **Size (Tamaño):** Tamaño formateado (`145.5 MB`).
  * **Type (Tipo):** Formato (`PDF`, `CURSO`).
  * **Date Imported / Modified:** Fechas legibles de registro y modificación.
* **Cero Muelle de Botones al Pie:** Se eliminan los botones redundantes de "Abrir Local", "Abrir Web" y "Papelera" del panel lateral.
  * **Apertura de Material:** Se realiza con **Doble Clic directo en la tarjeta del Grid**, abriendo según el modo activo en la barra superior (**Modo Local** con visor nativo de Windows o **Modo Web** en Google Drive).
* **Botón de Pin `📌`:** Superpuesto en la esquina superior derecha de la portada, con las mismas dimensiones de la etiqueta `PDF`, para anclar o desanclar el panel. No hay una cabecera visible de "INSPECTOR"; la portada comienza cerca del borde superior y aprovecha ese espacio.
* **Ojo en la barra superior:** Alterna la visibilidad de las etiquetas de tipo sobre las tarjetas, de la etiqueta de formato y del pin en la portada lateral. El estado se aplica directamente a los elementos visibles y a las tarjetas que se crean al desplazarse. Su elección se conserva entre aperturas cuando el almacenamiento local está disponible.
* **Corazón en la barra superior:** Activa o desactiva el filtro de favoritos guardados en la base de datos.
* **Estado en la barra superior:** Abre una lista de los cuatro estados de lectura y «Todos los estados». Elegir un estado reemplaza el filtro de estado anterior; la escritura de `@pendiente`, `@leyendo`, `@leido` y `@abandonado` sigue disponible.

### Navegación por teclado

La barra inferior de estado ya no ocupa espacio visible; sus mensajes siguen disponibles para lectores de pantalla. En el catálogo, las flechas izquierda y derecha avanzan entre tarjetas, y arriba y abajo saltan una fila según las columnas visibles. Inicio y Fin llevan al primer y último libro. La tarjeta enfocada actualiza la selección del panel lateral y el contorno de selección aparece solo alrededor de la portada, no de toda la tarjeta. Tab desde una tarjeta lleva a la portada del panel; Shift + Tab desde la portada vuelve a la tarjeta. Enter abre el archivo desde la tarjeta o la portada, y F2 permite acceder al control de estado de la tarjeta o elegir una imagen de portada cuando el foco está en la portada. El resto de controles del panel y de la barra superior siguen el orden normal de Tab.

---

## 5. Vista Interior de Cursos (Lanzador de Capítulos)

Al hacer doble clic en una tarjeta de tipo `CURSO` (ej. *Curso Blender 3D*), se entra en la vista interna enfocada:
* **Naturaleza:** Es un visor de capítulos/recursos, no un explorador de carpetas anidado.
* **Modo Lista Técnica:**
  * Tabla limpia de texto con icono SVG de formato (`.mp4`, `.blend`, `.pdf`), nombre del archivo y tamaño en disco.
  * Botón de lanzamiento directo con un solo clic (`os.startfile`).
  * Botón de acción rápida: eliminar archivo interno hacia la papelera (`send2trash`).
* **Botón de Escape:** `[ 📁 Abrir en Explorador de Windows ]` para tareas complejas en el explorador tradicional.
