"""Rules for the physical, profile-scoped Drive library."""
from pathlib import Path, PureWindowsPath
import os
import re
import shutil

from .database import preferencia, configurar
from .tags_manager import normalizar

INBOX = '_Inbox'
RESERVED = {'storage', 'containers', '.balisco', '.balisco_backup', '_inbox'}


def category_name(tag):
    name=str(tag or '').lstrip('+').casefold().strip()
    if (not name or name in RESERVED or name in {'.', '..'} or
            re.search(r'[<>:"/\\|?*\x00-\x1f]',name) or name.endswith((' ','.')) or
            name in {'con','prn','aux','nul',*(f'com{i}' for i in range(1,10)),*(f'lpt{i}' for i in range(1,10))}):
        raise ValueError('La etiqueta principal no puede usarse como nombre de carpeta')
    return name


def root_id(db, profile):
    return preferencia(db,'biblioteca_root_id:'+profile)


def mounted_drive(db, profile):
    configured=preferencia(db,'unidad_drive:'+profile)
    if configured:
        root=Path(configured).resolve()
        if (root/'Mi unidad').is_dir() or (root/'My Drive').is_dir(): return root
    if os.name!='nt': raise FileNotFoundError('La unidad de Google Drive no está montada')
    import ctypes
    mask=ctypes.windll.kernel32.GetLogicalDrives()
    drives=[Path(chr(65+n)+':/') for n in range(26) if mask & (1<<n)]
    matches=[drive for drive in drives if (drive/'Mi unidad').is_dir() or (drive/'My Drive').is_dir()]
    if not matches:raise FileNotFoundError('La unidad de Google Drive no está montada')
    if len(matches)!=1: raise ValueError('Selecciona la unidad de Google Drive del perfil activo')
    if configured and str(matches[0]).casefold()!=str(configured).casefold():
        with db:configurar(db,'unidad_drive:'+profile,str(matches[0]))
    return matches[0]


def root_parts(meta, drive_id):
    from .drive_sync import extraer_ids_proto
    for stable,node in meta.nodes.items():
        if not node['is_folder'] or node['trashed'] or node.get('is_tombstone'): continue
        try: ident=extraer_ids_proto(node['proto'])[0]
        except (ValueError,UnicodeError): continue
        if ident==drive_id:
            parts=meta.parts(stable)
            if parts and parts[0] in ('Mi unidad','My Drive') and len(parts)>1:
                return stable,parts
    return None,None


def library_root(db, profile):
    """Resolve a linked root afresh, so external renames and moves take effect."""
    from contextlib import closing
    from .drive_sync import Metadata, conectar_db_drive_ro, detectar_perfiles_drive
    ident=root_id(db,profile)
    if not ident: raise FileNotFoundError('Selecciona la ubicación de tu biblioteca')
    source=next((p['ruta_db'] for p in detectar_perfiles_drive() if p['id']==profile),None)
    if not source: raise FileNotFoundError('Los metadatos de Google Drive no están disponibles')
    with closing(conectar_db_drive_ro(source)) as conn:
        _,parts=root_parts(Metadata(conn),ident)
    if not parts: raise FileNotFoundError('La carpeta vinculada ya no existe en Google Drive')
    drive=mounted_drive(db,profile)
    path=drive.joinpath(*parts)
    if not path.is_dir(): raise FileNotFoundError('La carpeta vinculada no está disponible en la unidad de Drive')
    return path.resolve()


def relative_path(db, profile, target, root=None):
    root=Path(root or library_root(db,profile)).resolve()
    target=Path(target).resolve()
    if not target.is_relative_to(root): raise ValueError('Ruta fuera de la biblioteca')
    drive=mounted_drive(db,profile)
    return str(PureWindowsPath(*target.relative_to(drive).parts))


def _empty_category(folder):
    if folder.name.casefold() in RESERVED: return False
    if not folder.is_dir(): return False
    children=list(folder.iterdir())
    return all(child.is_file() and child.name.casefold()=='desktop.ini' for child in children)


def cleanup_category(folder):
    folder=Path(folder)
    if _empty_category(folder):
        for child in folder.iterdir(): child.unlink()
        folder.rmdir()


def preflight_moves(db, changes):
    """Reject invalid or colliding destinations before a multi-item edit begins."""
    roots={};drives={};targets=set()
    for item,tags in changes:
        if not item['disponible'] or item.get('container_parent'):continue
        profile=item['perfil_drive']
        if profile not in roots:
            roots[profile]=library_root(db,profile)
            drives[profile]=mounted_drive(db,profile)
        root=roots[profile]
        names=normalizar(' '.join(tags) if isinstance(tags,(list,tuple)) else tags)
        category=category_name(names[0]) if names else INBOX
        source=drives[profile].joinpath(*PureWindowsPath(item['ruta_relativa']).parts).resolve()
        if not source.is_relative_to(root) or source==root:raise ValueError('Ruta fuera de la biblioteca')
        target=root/category/source.name
        if source==target:continue
        if not source.exists():raise FileNotFoundError(str(source))
        key=str(target).casefold()
        if target.exists() or key in targets:raise FileExistsError('Ya existe un elemento en '+str(target))
        targets.add(key)


def move_primary(db, item, tags, root=None):
    """Move a top-level item before updating its tags; leave database unchanged on failure."""
    root=Path(root or library_root(db,item['perfil_drive'])).resolve()
    tags=normalizar(' '.join(tags) if isinstance(tags,(list,tuple)) else tags)
    category=category_name(tags[0]) if tags else INBOX
    source=mounted_drive(db,item['perfil_drive']).joinpath(*PureWindowsPath(item['ruta_relativa']).parts).resolve()
    if not source.is_relative_to(root) or source==root: raise ValueError('Ruta fuera de la biblioteca')
    if item.get('container_parent'):
        raise ValueError('Los recursos internos heredan la carpeta del contenedor')
    destination_dir=root/category
    destination=destination_dir/source.name
    if source!=destination:
        if not source.exists(): raise FileNotFoundError(str(source))
        if destination.exists(): raise FileExistsError('Ya existe un elemento con ese nombre en '+category)
        destination_dir.mkdir(exist_ok=True)
        shutil.move(str(source),str(destination))
        old_relative=item['ruta_relativa']
        new_relative=relative_path(db,item['perfil_drive'],destination,root)
        try:
            with db:
                db.execute('UPDATE items SET ruta_relativa=?,categoria_macro=?,subcategoria=?,etiquetas=? WHERE id=?',
                           (new_relative,category,'',' '.join('+'+tag for tag in tags),item['id']))
                if item['tipo']=='curso':
                    old_prefix=old_relative+'\\'
                    new_prefix=new_relative+'\\'
                    for table in ('items','container_entries'):
                        db.execute('UPDATE '+table+' SET ruta_relativa=? || substr(ruta_relativa,?) WHERE perfil_drive=? AND substr(ruta_relativa,1,?)=?',
                                   (new_prefix,len(old_prefix)+1,item['perfil_drive'],len(old_prefix),old_prefix))
                db.execute('''INSERT INTO pending_container_moves(drive_id,expected_relative,container_drive_id,perfil_drive)
                    VALUES(?,?,?,?) ON CONFLICT(drive_id) DO UPDATE SET expected_relative=excluded.expected_relative,
                    container_drive_id=excluded.container_drive_id,perfil_drive=excluded.perfil_drive,created_at=CURRENT_TIMESTAMP''',
                    (item['drive_id'],new_relative,item.get('container_parent',''),item['perfil_drive']))
        except Exception:
            shutil.move(str(destination),str(source))
            raise
        cleanup_category(source.parent)
    else:
        with db:
            db.execute('UPDATE items SET etiquetas=? WHERE id=?',(' '.join('+'+tag for tag in tags),item['id']))
    return new_relative if source!=destination else item['ruta_relativa']
