from pathlib import Path, PureWindowsPath
import os
import sqlite3
import unicodedata
import re

DATA_DIR = Path(os.environ.get("BALISCO_DATA_DIR", str(Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Balisco")))
STATES = ("pendiente", "interesado", "leyendo", "leido", "abandonado")

def normalize_tag(text):
    if not text:
        return ''
    norm = ''.join(c for c in unicodedata.normalize('NFKD', str(text)) if not unicodedata.combining(c))
    return norm.replace('_', '-').casefold()

def normalize_search(text):
    if not text:
        return ''
    norm = ''.join(c for c in unicodedata.normalize('NFKD', str(text)) if not unicodedata.combining(c))
    norm = re.sub(r'[-_\s]+', ' ', norm)
    return norm.strip().casefold()

def conectar(path=None):
    path = Path(path) if path else DATA_DIR / "biblioteca.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.create_function('unicode_casefold',1,lambda value: str(value or '').casefold(),deterministic=True)
    db.create_function('normalize_tag',1,normalize_tag,deterministic=True)
    db.create_function('normalize_search',1,normalize_search,deterministic=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA encoding='UTF-8'")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS items (
      id INTEGER PRIMARY KEY AUTOINCREMENT, drive_id TEXT NOT NULL UNIQUE,
      titulo TEXT NOT NULL, autor TEXT NOT NULL DEFAULT '',
      idioma TEXT NOT NULL DEFAULT '',
      tipo TEXT NOT NULL CHECK(tipo IN ('pdf','curso','video','audio','imagen','archivo')),
      tipo_contenido TEXT NOT NULL DEFAULT '', formato TEXT NOT NULL DEFAULT '',
      categoria_macro TEXT DEFAULT 'General', subcategoria TEXT DEFAULT '',
      etiquetas TEXT DEFAULT '', descripcion TEXT DEFAULT '', notas TEXT DEFAULT '',
      estado_lectura TEXT DEFAULT 'pendiente' CHECK(estado_lectura IN ('pendiente','interesado','leyendo','leido','abandonado')),
      rating INTEGER DEFAULT 0 CHECK(rating BETWEEN 0 AND 5),
      es_favorito INTEGER DEFAULT 0 CHECK(es_favorito IN (0,1)),
      ruta_relativa TEXT NOT NULL, ruta_portada TEXT, tamano_bytes INTEGER DEFAULT 0,
      mime_type TEXT, fecha_agregado TIMESTAMP DEFAULT CURRENT_TIMESTAMP, ultimo_acceso TIMESTAMP,
      titulo_personalizado INTEGER NOT NULL DEFAULT 0, perfil_drive TEXT NOT NULL DEFAULT '', disponible INTEGER NOT NULL DEFAULT 1,
      indexar_contenido INTEGER NOT NULL DEFAULT 0 CHECK(indexar_contenido IN (0,1)),
      oculto INTEGER NOT NULL DEFAULT 0 CHECK(oculto IN (0,1)),
      container_parent TEXT NOT NULL DEFAULT '',
      fijado INTEGER NOT NULL DEFAULT 0 CHECK(fijado IN (0,1)),
      search_override INTEGER NOT NULL DEFAULT -1 CHECK(search_override IN (-1,0,1)),
      recent_hidden INTEGER NOT NULL DEFAULT 0 CHECK(recent_hidden IN (0,1)),
      mostrar_en_filtros INTEGER NOT NULL DEFAULT 1 CHECK(mostrar_en_filtros IN (0,1))
    );
    CREATE INDEX IF NOT EXISTS idx_items_busqueda ON items(categoria_macro,subcategoria,estado_lectura,rating,es_favorito);
    CREATE INDEX IF NOT EXISTS idx_items_perfil ON items(perfil_drive,disponible);
    CREATE INDEX IF NOT EXISTS idx_items_profile_path ON items(perfil_drive,ruta_relativa);
    CREATE TABLE IF NOT EXISTS container_entries (
      id INTEGER PRIMARY KEY, container_drive_id TEXT NOT NULL, drive_id TEXT NOT NULL UNIQUE,
      titulo TEXT NOT NULL, ruta_relativa TEXT NOT NULL, tamano_bytes INTEGER NOT NULL DEFAULT 0,
      mime_type TEXT, perfil_drive TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_container_entries_parent ON container_entries(container_drive_id,perfil_drive);
    CREATE INDEX IF NOT EXISTS idx_container_entries_profile_path ON container_entries(perfil_drive,ruta_relativa);
    CREATE TABLE IF NOT EXISTS pending_container_moves (
      drive_id TEXT PRIMARY KEY, expected_relative TEXT NOT NULL,
      container_drive_id TEXT NOT NULL, perfil_drive TEXT NOT NULL,
      created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    DROP TRIGGER IF EXISTS container_entries_ai;
    DROP TRIGGER IF EXISTS container_entries_ad;
    DROP TRIGGER IF EXISTS container_entries_au;
    DROP TABLE IF EXISTS container_entries_fts;
    CREATE TABLE IF NOT EXISTS configuracion(clave TEXT PRIMARY KEY, valor TEXT NOT NULL);
    CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(titulo,autor,etiquetas,notas,categoria_macro,subcategoria,content='items',content_rowid='id',tokenize='unicode61 remove_diacritics 2');
    CREATE TRIGGER IF NOT EXISTS items_ai AFTER INSERT ON items BEGIN
      INSERT INTO items_fts(rowid,titulo,autor,etiquetas,notas,categoria_macro,subcategoria) VALUES(new.id,new.titulo,new.autor,new.etiquetas,new.notas,new.categoria_macro,new.subcategoria);
    END;
    CREATE TRIGGER IF NOT EXISTS items_ad AFTER DELETE ON items BEGIN
      INSERT INTO items_fts(items_fts,rowid,titulo,autor,etiquetas,notas,categoria_macro,subcategoria) VALUES('delete',old.id,old.titulo,old.autor,old.etiquetas,old.notas,old.categoria_macro,old.subcategoria);
    END;
    CREATE TRIGGER IF NOT EXISTS items_au AFTER UPDATE OF titulo,autor,etiquetas,notas,categoria_macro,subcategoria ON items BEGIN
      INSERT INTO items_fts(items_fts,rowid,titulo,autor,etiquetas,notas,categoria_macro,subcategoria) VALUES('delete',old.id,old.titulo,old.autor,old.etiquetas,old.notas,old.categoria_macro,old.subcategoria);
      INSERT INTO items_fts(rowid,titulo,autor,etiquetas,notas,categoria_macro,subcategoria) VALUES(new.id,new.titulo,new.autor,new.etiquetas,new.notas,new.categoria_macro,new.subcategoria);
    END;
    """)
    columns={row[1] for row in db.execute('PRAGMA table_info(items)')}
    if 'idioma' not in columns:
        db.execute("ALTER TABLE items ADD COLUMN idioma TEXT NOT NULL DEFAULT ''")
    db.execute("INSERT OR IGNORE INTO configuracion(clave, valor) VALUES ('idiomas', '[\"Español\", \"Inglés\"]')")
    if 'indexar_contenido' not in columns:
        db.execute('ALTER TABLE items ADD COLUMN indexar_contenido INTEGER NOT NULL DEFAULT 0 CHECK(indexar_contenido IN (0,1))')
    if 'oculto' not in columns:
        db.execute('ALTER TABLE items ADD COLUMN oculto INTEGER NOT NULL DEFAULT 0 CHECK(oculto IN (0,1))')
    if 'tipo_contenido' not in columns:
        db.execute("ALTER TABLE items ADD COLUMN tipo_contenido TEXT NOT NULL DEFAULT ''")
    if 'formato' not in columns:
        db.execute("ALTER TABLE items ADD COLUMN formato TEXT NOT NULL DEFAULT ''")
    for column,definition in (
        ('container_parent',"TEXT NOT NULL DEFAULT ''"),
        ('fijado','INTEGER NOT NULL DEFAULT 0'),
        ('search_override','INTEGER NOT NULL DEFAULT -1'),
        ('recent_hidden','INTEGER NOT NULL DEFAULT 0'),
        ('mostrar_en_filtros','INTEGER NOT NULL DEFAULT 1')):
        if column not in columns: db.execute('ALTER TABLE items ADD COLUMN '+column+' '+definition)
    db.execute('CREATE INDEX IF NOT EXISTS idx_items_scope ON items(perfil_drive,disponible,container_parent,oculto)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_items_history ON items(perfil_drive,recent_hidden,ultimo_acceso DESC)')
    db.execute("CREATE INDEX IF NOT EXISTS idx_items_etiquetas_partial ON items(perfil_drive,disponible,oculto) WHERE etiquetas != ''")
    db.execute('CREATE INDEX IF NOT EXISTS idx_items_parent ON items(container_parent,disponible)')
    missing=db.execute("SELECT id,tipo,ruta_relativa FROM items WHERE tipo_contenido='' OR (formato='' AND tipo!='curso')").fetchall()
    if missing:
        def content_type(row):
            if row['tipo']=='curso': return 'contenedor'
            if row['tipo']=='pdf': return 'documento'
            path=PureWindowsPath(row['ruta_relativa'])
            parts=path.parts
            if row['tipo']=='archivo' and len(parts)==4 and parts[2].casefold()=='containers' and path.suffix.casefold() in ('.zip','.rar'):
                return 'contenedor'
            return 'otro' if row['tipo']=='archivo' else row['tipo']
        db.executemany('UPDATE items SET tipo_contenido=?,formato=? WHERE id=?',[
            (content_type(row),
             '' if row['tipo']=='curso' else PureWindowsPath(row['ruta_relativa']).suffix.lstrip('.').upper(),row['id'])
            for row in missing])
        db.commit()
    if {'folder_kind','group_id','group_manual'} & columns:
        db.execute('''UPDATE items SET disponible=0 WHERE EXISTS (
            SELECT 1 FROM items parent WHERE parent.tipo='curso' AND parent.perfil_drive=items.perfil_drive
            AND items.ruta_relativa LIKE parent.ruta_relativa || char(92) || '%' AND parent.id!=items.id)''')
        db.execute('DROP INDEX IF EXISTS idx_items_group')
        for legacy in ('group_manual','group_id','folder_kind'):
            if legacy in columns: db.execute('ALTER TABLE items DROP COLUMN '+legacy)
    return db

def configurar(db, clave, valor):
    db.execute("INSERT INTO configuracion VALUES(?,?) ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor", (clave,str(valor)))

def preferencia(db, clave, default=None):
    row=db.execute("SELECT valor FROM configuracion WHERE clave=?",(clave,)).fetchone()
    return row[0] if row else default
