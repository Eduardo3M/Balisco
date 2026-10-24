"""Upgrade existing phase-1 catalogs without losing user metadata."""
from contextlib import closing
from pathlib import Path
import sqlite3

def migrate_interested(path):
    """Expand the existing items CHECK constraint while preserving data and indexes."""
    path=Path(path)
    if not path.exists(): return False
    with closing(sqlite3.connect(path)) as db:
        row=db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='items'").fetchone()
        if not row or "'interesado'" in row[0]: return False
        old="'pendiente','leyendo','leido','abandonado'"
        if old not in row[0]: raise RuntimeError('Esquema de estados desconocido')
        backup=path.with_name('biblioteca.pre-interesado.db')
        if not backup.exists():
            with closing(sqlite3.connect(backup)) as copy: db.backup(copy)
        objects=[(kind,name,sql) for kind,name,sql in db.execute("SELECT type,name,sql FROM sqlite_master WHERE tbl_name='items' AND type IN ('index','trigger') AND sql IS NOT NULL")]
        db.execute('PRAGMA foreign_keys=OFF')
        try:
            db.execute('BEGIN IMMEDIATE')
            for kind,name,_ in objects: db.execute('DROP '+('INDEX' if kind=='index' else 'TRIGGER')+' IF EXISTS "'+name+'"')
            db.execute('ALTER TABLE items RENAME TO items_old_state')
            db.execute(row[0].replace(old,"'pendiente','interesado','leyendo','leido','abandonado'"))
            columns=[r[1] for r in db.execute('PRAGMA table_info(items)')]
            names=','.join('"'+c+'"' for c in columns)
            db.execute(f'INSERT INTO items({names}) SELECT {names} FROM items_old_state')
            db.execute('DROP TABLE items_old_state')
            for _,_,sql in objects: db.execute(sql)
            db.execute('COMMIT')
        except Exception:
            db.execute('ROLLBACK')
            raise
        return True

def migrate_author(path):
    path=Path(path)
    if not path.exists(): return False
    with closing(sqlite3.connect(path)) as db:
        columns={r[1] for r in db.execute('PRAGMA table_info(items)')}
        fts={r[1] for r in db.execute('PRAGMA table_info(items_fts)')}
        if not columns or ('autor' in columns and 'autor' in fts): return False
        backup=path.with_name('biblioteca.pre-autor.db')
        if not backup.exists():
            with closing(sqlite3.connect(backup)) as copy: db.backup(copy)
        with db:
            db.execute('BEGIN IMMEDIATE')
            if 'autor' not in columns: db.execute("ALTER TABLE items ADD COLUMN autor TEXT NOT NULL DEFAULT ''")
            for trigger in ('items_ai','items_ad','items_au'): db.execute('DROP TRIGGER IF EXISTS '+trigger)
            db.execute('DROP TABLE IF EXISTS items_fts')
            db.execute("CREATE VIRTUAL TABLE items_fts USING fts5(titulo,autor,etiquetas,notas,categoria_macro,subcategoria,content='items',content_rowid='id',tokenize='unicode61 remove_diacritics 2')")
            db.execute("INSERT INTO items_fts(items_fts) VALUES('rebuild')")
            columns='titulo,autor,etiquetas,notas,categoria_macro,subcategoria'
            new=','.join('new.'+c for c in columns.split(',')); old=','.join('old.'+c for c in columns.split(','))
            db.execute(f'CREATE TRIGGER items_ai AFTER INSERT ON items BEGIN INSERT INTO items_fts(rowid,{columns}) VALUES(new.id,{new}); END')
            db.execute(f"CREATE TRIGGER items_ad AFTER DELETE ON items BEGIN INSERT INTO items_fts(items_fts,rowid,{columns}) VALUES('delete',old.id,{old}); END")
            db.execute(f"CREATE TRIGGER items_au AFTER UPDATE OF {columns} ON items BEGIN INSERT INTO items_fts(items_fts,rowid,{columns}) VALUES('delete',old.id,{old}); INSERT INTO items_fts(rowid,{columns}) VALUES(new.id,{new}); END")
        return True
