from pathlib import Path
import os
import sqlite3

DATA_DIR = Path(os.environ.get("BALISCO_DATA_DIR", str(Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Balisco")))
STATES = ("pendiente", "interesado", "leyendo", "leido", "abandonado")

def conectar(path=None):
    path = Path(path) if path else DATA_DIR / "biblioteca.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.create_function('unicode_casefold',1,lambda value: str(value or '').casefold(),deterministic=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA encoding='UTF-8'")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS items (
      id INTEGER PRIMARY KEY AUTOINCREMENT, drive_id TEXT NOT NULL UNIQUE,
      titulo TEXT NOT NULL, autor TEXT NOT NULL DEFAULT '',
      tipo TEXT NOT NULL CHECK(tipo IN ('pdf','curso','video')),
      categoria_macro TEXT DEFAULT 'General', subcategoria TEXT DEFAULT '',
      etiquetas TEXT DEFAULT '', descripcion TEXT DEFAULT '', notas TEXT DEFAULT '',
      estado_lectura TEXT DEFAULT 'pendiente' CHECK(estado_lectura IN ('pendiente','interesado','leyendo','leido','abandonado')),
      rating INTEGER DEFAULT 0 CHECK(rating BETWEEN 0 AND 5),
      es_favorito INTEGER DEFAULT 0 CHECK(es_favorito IN (0,1)),
      ruta_relativa TEXT NOT NULL, ruta_portada TEXT, tamano_bytes INTEGER DEFAULT 0,
      mime_type TEXT, fecha_agregado TIMESTAMP DEFAULT CURRENT_TIMESTAMP, ultimo_acceso TIMESTAMP,
      titulo_personalizado INTEGER NOT NULL DEFAULT 0, perfil_drive TEXT NOT NULL DEFAULT '', disponible INTEGER NOT NULL DEFAULT 1
    );
    CREATE INDEX IF NOT EXISTS idx_items_busqueda ON items(categoria_macro,subcategoria,estado_lectura,rating,es_favorito);
    CREATE INDEX IF NOT EXISTS idx_items_perfil ON items(perfil_drive,disponible);
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
    return db

def configurar(db, clave, valor):
    db.execute("INSERT INTO configuracion VALUES(?,?) ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor", (clave,str(valor)))

def preferencia(db, clave, default=None):
    row=db.execute("SELECT valor FROM configuracion WHERE clave=?",(clave,)).fetchone()
    return row[0] if row else default
