import re
import sqlite3
from pathlib import Path

def clean_book_title_and_author(raw_name: str, tipo: str = 'pdf'):
    """
    Limpia estéticamente el título de un libro o curso y extrae el autor.
    Elimina extensiones (.pdf, .epub), identificadores web (Anna's Archive, Libgen, Z-Lib),
    hashes MD5, ISBNs sobrantes, corchetes y caracteres residuales.
    """
    if tipo == 'curso':
        # En cursos preservamos el nombre del directorio pero normalizamos espacios
        name = re.sub(r'[\r\n\t]+', ' ', raw_name).strip()
        name = re.sub(r'\s{2,}', ' ', name)
        return name, ""

    name = raw_name.strip()

    # 1. Quitar extensiones de archivo
    name = re.sub(r'\.(pdf|epub|azw3?|mobi|kfx|fb2|djvu?|cbz|cbr|cb7|lit|pdb|txt|rtf|lrf|kepub)$', '', name, flags=re.I).strip()

    # 2. Quitar prefijos de webs comunes (ej: pdfcoffee.com_)
    name = re.sub(r'^(?:pdfcoffee\.com|libgen\.[a-z]+|z-lib(?:rary)?\.[a-z]+)[_\s-]+', '', name, flags=re.I).strip()

    # 3. Quitar sufijos de procedencia y webs
    name = re.sub(r'\s*--\s*(?:Anna.?s\s*Archive|Libgen(?:\.[a-z]+)?|Z-Library|PDF\s*Room).*$', '', name, flags=re.I).strip()
    name = re.sub(r'\s*-\s*libgen\.[a-z0-9]+.*$', '', name, flags=re.I).strip()
    name = re.sub(r'\s*\([^)]*(?:Z-Library|libgen|1lib|z-lib)[^)]*\).*$', '', name, flags=re.I).strip()
    name = re.sub(r'\s*-\s*PDF\s*Room.*$', '', name, flags=re.I).strip()
    name = re.sub(r'_compress$', '', name, flags=re.I).strip()
    name = re.sub(r'-pdf-free$', '', name, flags=re.I).strip()

    # Quitar corchetes iniciales informativos como [Evil Genius] o [Ciencia]
    name = re.sub(r'^\s*\[[^\]]+\]\s*', '', name).strip()

    autor = ""

    # 4. Caso Anna's Archive: Separado por ' -- '
    # Ej: "Titulo _ Subtitulo -- Autor -- Año, Edición -- Editorial -- ISBN -- Hash"
    parts = [p.strip() for p in re.split(r'\s*--\s*', name) if p.strip()]
    if len(parts) >= 2:
        title_part = parts[0]
        potential_author = parts[1]
        # Si parts[1] no es un año o hash o ISBN
        if not re.match(r'^\d{4}$|^97[89]\d|^[a-f0-9]{20,}$', potential_author, re.I):
            autor = potential_author
        name = title_part

    # 5. Comprobar paréntesis al final con autor: "Titulo (Gareth Branwyn)" o "(Wachter-Boettcher, Sara, author)"
    if not autor:
        m_paren = re.search(r'\(([^)]+)\)$', name)
        if m_paren:
            inside = m_paren.group(1).strip()
            # Si parece autor (no contiene palabras de edición, editorial o números)
            if not re.search(r'\b(edici[oó]n|edition|vol|volumen|press|editorial|\d{4})\b', inside, re.I):
                # Quitar ", author"
                clean_inside = re.sub(r',?\s*author\b', '', inside, flags=re.I).strip()
                if len(clean_inside.split()) in (2, 3, 4) or ',' in clean_inside:
                    autor = clean_inside
                    name = name[:m_paren.start()].strip()

    # 6. Separación por guión: "A - B"
    if not autor and ' - ' in name:
        dash_parts = name.split(' - ')
        if len(dash_parts) == 2:
            p1, p2 = dash_parts[0].strip(), dash_parts[1].strip()

            # Caso A: "Apellido, Nombre - Titulo"
            if re.match(r'^[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+,\s*[A-ZÁÉÍÓÚÑ]', p1):
                autor = p1
                name = p2
            # Caso B: "Titulo - Nombre Apellido" (p2 son 2-4 palabras de nombre propio)
            elif re.match(r'^[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,3}$', p2):
                autor = p2
                name = p1
            # Caso C: "Autor 1, Autor 2 - Titulo" (p1 contiene autores múltiples con nombres propios)
            elif (re.match(r'^[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ\.]+)+,\s*[A-ZÁÉÍÓÚÑ]', p1)
                  and not any(p1.startswith(na) for na in ('The ', 'El ', 'La ', 'Los ', 'Las '))):
                autor = p1
                name = p2
            # Caso D: "Nombre Apellido - Titulo"
            elif re.match(r'^[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,2}$', p1):
                non_authors = ('El ', 'La ', 'Los ', 'Las ', 'The ', 'Un ', 'Una ', 'Make ', 'Mini ', 'Como ', 'Que ')
                if not any(p1.startswith(na) for na in non_authors):
                    autor = p1
                    name = p2

    # 7. Quitar año y editorial entre paréntesis al final si quedó
    name = re.sub(r'\s*\(\d{4}(?:,\s*[^)]+)?\)$', '', name).strip()
    name = re.sub(r'\s*\[[^\]]+\]\s*', '', name).strip()

    # 8. Limpieza tipográfica del título:
    # Quitar underscores alrededor de palabras: _Guardias_ -> Guardias
    name = re.sub(r'(?:^|\s)_+([^_]+)_+(?=\s|$)', r' \1 ', name).strip()
    # Quitar underscores al final de palabras: Guardias_ -> Guardias
    name = re.sub(r'(\w)_+(?=\s|$)', r'\1', name).strip()
    # Quitar underscores al inicio de palabras: _Guardias -> Guardias
    name = re.sub(r'(?:^|\s)_+(\w)', r' \1', name).strip()

    # Reemplazar " _ " por ": " (separador de título y subtítulo)
    name = re.sub(r'\s*_\s+', ': ', name)

    # Si todo son underscores o guiones sin espacios (formato slug):
    if '_' in name and ' ' not in name:
        name = name.replace('_', ' ')
    if '-' in name and ' ' not in name and len(name) > 20:
        name = name.replace('-', ' ')

    # Corregir signos de exclamación e interrogación en español:
    # !Palabra! -> ¡Palabra!
    name = re.sub(r'(?:^|\s)!([A-ZÁÉÍÓÚa-záéíóú0-9¿¡\s]+)!', r' ¡\1!', name).strip()
    if name.startswith('!') and '!' in name[1:]:
        name = '¡' + name[1:]
    # ?Palabra? -> ¿Palabra?
    name = re.sub(r'(?:^|\s)\?([A-ZÁÉÍÓÚa-záéíóú0-9¿¡\s]+)\?', r' ¿\1?', name).strip()
    if name.startswith('?') and '?' in name[1:]:
        name = '¿' + name[1:]

    # Quitar puntuación huérfana al final
    name = re.sub(r'[\s,:_\-]+$', '', name).strip()
    name = re.sub(r'\s{2,}', ' ', name).strip()

    # 9. Limpieza y formateo del autor:
    if autor:
        autor = re.sub(r'[\s,:;_\-]+$', '', autor).strip()
        # "Apellido, Nombre" -> "Nombre Apellido"
        m_rev = re.match(r'^([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+),\s*([A-ZÁÉÍÓÚÑ][a-záéíóúñ\.\s]+)$', autor)
        if m_rev:
            autor = f"{m_rev.group(2).strip()} {m_rev.group(1).strip()}"
        # Quitar sufijos de año como ", 1978-" o "(ed.)"
        autor = re.sub(r',?\s*\d{4}-?$', '', autor).strip()
        autor = re.sub(r'\s*\(ed\.?\)', '', autor, flags=re.I).strip()
        autor = re.sub(r'\s{2,}', ' ', autor).strip()

    return name, autor

def limpiar_biblioteca_db(db):
    """
    Recorre todos los items con titulo_personalizado=0 y aplica la limpieza
    estética a títulos y autores, actualizando SQLite y los índices FTS5.
    """
    cursor = db.execute("SELECT id, titulo, autor, tipo FROM items WHERE titulo_personalizado=0")
    rows = cursor.fetchall()

    actualizados = 0
    autores_agregados = 0

    with db:
        for r in rows:
            clean_title, clean_author = clean_book_title_and_author(r['titulo'], r['tipo'])
            new_title = clean_title if clean_title else r['titulo']
            # Conservar los autores editados por el usuario durante una limpieza posterior.
            new_author = r['autor'] or clean_author

            if new_title != r['titulo'] or new_author != r['autor']:
                db.execute(
                    "UPDATE items SET titulo=?, autor=? WHERE id=?",
                    (new_title, new_author, r['id'])
                )
                actualizados += 1
                if clean_author and not r['autor']:
                    autores_agregados += 1

    return {
        'total': len(rows),
        'actualizados': actualizados,
        'autores_agregados': autores_agregados
    }
