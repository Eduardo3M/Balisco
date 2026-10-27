from datetime import datetime
from pathlib import Path
import os
import shutil
import sqlite3
import tempfile
import zipfile
from .database import DATA_DIR

def _db_dir(conexion_db):
    try:
        row=conexion_db.execute('PRAGMA database_list').fetchone()
        if row and row[2]: return Path(row[2]).parent
    except Exception:
        pass
    return DATA_DIR


def crear_backup_en_drive(ruta_letra_drive, conexion_db, directorio_datos=None, nombre_unidad='Mi unidad'):
    """Snapshot SQLite online; solo comprime datos locales de Balisco."""
    data=Path(directorio_datos) if directorio_datos else _db_dir(conexion_db)
    library=Path(ruta_letra_drive)/nombre_unidad/'Biblioteca'
    if not library.is_dir(): raise FileNotFoundError('Biblioteca no montada')
    destination=library/'.balisco_backup'
    destination.mkdir(exist_ok=True)
    name='Balisco_Backup_'+datetime.now().strftime('%Y-%m-%d_%H%M%S_%f')+'.zip'
    target=destination/name
    if conexion_db.in_transaction:
        try: conexion_db.commit()
        except Exception: pass
    with tempfile.TemporaryDirectory(prefix='balisco-backup-') as tmp:
        snapshot=Path(tmp)/'biblioteca.db'
        copied=sqlite3.connect(snapshot)
        try: conexion_db.backup(copied)
        finally: copied.close()
        archive=Path(tmp)/name
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            z.write(snapshot,'biblioteca.db')
            covers=data/'portadas'
            if covers.exists():
                for cover in covers.glob('*.jpg'):
                    if cover.is_file() and not cover.is_symlink(): z.write(cover,'portadas/'+cover.name)
        partial=destination/(name+'.partial')
        try:
            shutil.copyfile(archive,partial)
            os.replace(partial,target)
        finally: partial.unlink(missing_ok=True)
    return str(target)


def crear_backup_en_biblioteca(library, conexion_db, directorio_datos=None):
    """Create a backup directly in the already resolved active Drive library."""
    library=Path(library)
    if not library.is_dir(): raise FileNotFoundError('Biblioteca no montada')
    data=Path(directorio_datos) if directorio_datos else _db_dir(conexion_db)
    destination=library/'.balisco'/'backups'
    destination.mkdir(parents=True,exist_ok=True)
    name='Balisco_Backup_'+datetime.now().strftime('%Y-%m-%d_%H%M%S_%f')+'.zip'
    target=destination/name
    if conexion_db.in_transaction:
        try: conexion_db.commit()
        except Exception: pass
    with tempfile.TemporaryDirectory(prefix='balisco-backup-') as tmp:
        snapshot=Path(tmp)/'biblioteca.db'
        copied=sqlite3.connect(snapshot)
        try: conexion_db.backup(copied)
        finally: copied.close()
        archive=Path(tmp)/name
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            z.write(snapshot,'biblioteca.db')
            covers=data/'portadas'
            if covers.exists():
                for cover in covers.glob('*.jpg'):
                    if cover.is_file() and not cover.is_symlink(): z.write(cover,'portadas/'+cover.name)
        partial=destination/(name+'.partial')
        try:
            shutil.copyfile(archive,partial)
            os.replace(partial,target)
        finally: partial.unlink(missing_ok=True)
    return str(target)
