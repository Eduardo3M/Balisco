"""Physical operations in the mounted Google Drive library."""
from contextlib import closing
from pathlib import Path, PureWindowsPath
import re
import shutil
import time
import os
import logging

from .database import preferencia
from .drive_sync import Metadata, conectar_db_drive_ro, detectar_perfiles_drive, extraer_ids_proto, obtener_letra_drive, classify_file
from .items_manager import ItemsManager
from .cleaner import clean_book_title_and_author
from .library_layout import root_id, relative_path, INBOX, category_name, cleanup_category
from .tags_manager import normalizar


class ImportCancelled(Exception):
    pass


def _windows_folder_metadata(name):
    return name.casefold()=='desktop.ini'


def _check_cancelled(cancelled):
    if cancelled and cancelled():raise ImportCancelled('Importación cancelada. Los archivos que ya se copiaron permanecen en Drive.')


def _copy_file(source,destination,cancelled=None,progress=None,stats=None,label=''):
    source=Path(source);destination=Path(destination);size=source.stat().st_size
    destination.parent.mkdir(parents=True,exist_ok=True)
    written=0;last_update=0
    with source.open('rb') as src,destination.open('wb') as dst:
        while True:
            _check_cancelled(cancelled)
            block=src.read(4*1024*1024)
            if not block:break
            dst.write(block);written+=len(block)
            if stats is not None:stats['bytes_current']=stats.get('bytes_current',0)+len(block)
            now=time.monotonic()
            if progress and (now-last_update>=.5 or written==size):
                amount=stats.get('bytes_current',written) if stats else written
                total=stats.get('bytes_total',size) if stats else size
                local_pct=100 if total==0 else min(100,int(amount*100/total))
                pct=min(70,10+round(local_pct*.6/5)*5)
                bucket=stats.setdefault('last_pct',-1) if stats else -1
                if pct!=bucket:
                    if stats is not None:stats['last_pct']=pct
                    progress('copiando',f'{label} · aprox. {pct}%')
                    last_update=now
    shutil.copystat(source,destination)
    if written!=size:raise IOError(f'Copia incompleta: {source.name}')
    if stats is not None:
        stats['files_done']=stats.get('files_done',0)+1
        pct=min(70,10+round((100 if not stats['bytes_total'] else stats['bytes_current']*100/stats['bytes_total'])*.6/5)*5)
        if progress and pct!=stats.get('last_pct'):
            stats['last_pct']=pct;progress('copiando',f'{label} · aprox. {pct}%')
    return str(destination)


def _manifest(root,cancelled=None):
    root=Path(root);files=[];directories=[]
    for current,dirs,names in os.walk(root,followlinks=False):
        _check_cancelled(cancelled)
        current=Path(current)
        if current!=root:directories.append(current.relative_to(root))
        for name in [*dirs,*names]:
            _check_cancelled(cancelled)
            if (current/name).is_symlink():raise ValueError('La carpeta contiene enlaces simbólicos y no se puede importar completa')
        dirs.sort(key=str.casefold);names.sort(key=str.casefold)
        for name in names:
            _check_cancelled(cancelled)
            if _windows_folder_metadata(name):continue
            path=current/name
            files.append((path.relative_to(root),path.stat().st_size))
    return files,directories


def _copy_tree(source,target,cancelled,progress,stats,label,create_root=True):
    source=Path(source);target=Path(target);_check_cancelled(cancelled)
    if create_root:target.mkdir()
    with os.scandir(source) as listing:entries=sorted(listing,key=lambda entry:entry.name.casefold())
    for entry in entries:
        _check_cancelled(cancelled)
        if _windows_folder_metadata(entry.name) and entry.is_file(follow_symlinks=False):continue
        src=Path(entry.path);dst=target/entry.name
        if entry.is_symlink():raise ValueError('La carpeta contiene enlaces simbólicos y no se puede importar completa')
        if entry.is_dir(follow_symlinks=False):_copy_tree(src,dst,cancelled,progress,stats,label)
        elif entry.is_file(follow_symlinks=False):_copy_file(src,dst,cancelled,progress,stats,label)
        else:raise ValueError(f'Elemento no compatible dentro de la carpeta: {entry.name}')
    shutil.copystat(source,target)


def _verify_copy(source,target,manifest,directories=(),cancelled=None):
    _check_cancelled(cancelled)
    if not Path(target).is_dir():raise IOError('No se pudo verificar la carpeta copiada')
    for relative in directories:
        _check_cancelled(cancelled)
        if not (Path(target)/relative).is_dir():raise IOError(f'No se pudo verificar la carpeta “{relative}”')
    for relative,size in manifest:
        _check_cancelled(cancelled)
        path=Path(target)/relative
        if not path.is_file() or path.stat().st_size!=size:
            raise IOError(f'No se pudo verificar la copia de “{relative}”')


def library_root(db, profile):
    if root_id(db,profile):
        from .library_layout import library_root as linked_root
        return linked_root(db,profile)
    root=Path(preferencia(db,'unidad_drive:'+profile) or obtener_letra_drive()).resolve()
    for name in ('Mi unidad','My Drive'):
        candidate=root/name/'Biblioteca'
        if candidate.is_dir(): return candidate.resolve()
    raise FileNotFoundError('No se encontró Biblioteca en la unidad de Drive')


def inside(path, root):
    resolved=path.resolve()
    if not resolved.is_relative_to(root) or resolved==root:
        raise ValueError('Ruta fuera de Biblioteca')
    return resolved


def valid_name(value):
    name=str(value or '').strip()
    if not name or name.startswith('.') or name in ('.','..') or re.search(r'[<>:"/\\|?*\x00-\x1f]',name) or name.endswith((' ','.')):
        raise ValueError('Nombre de contenedor inválido')
    if name.casefold() in {'con','prn','aux','nul',*(f'com{i}' for i in range(1,10)),*(f'lpt{i}' for i in range(1,10))}:
        raise ValueError('Nombre reservado por Windows')
    return name


def drive_id_for_path(profile, relative, timeout=60, progress=None, is_folder=None, cancelled=None, allow_hidden=False):
    source=next((p['ruta_db'] for p in detectar_perfiles_drive() if p['id']==profile),None)
    if not source: raise FileNotFoundError('Metadatos de Drive no disponibles')
    expected=tuple(PureWindowsPath(relative).parts)
    deadline=time.monotonic()+timeout
    announced=False
    while True:
        _check_cancelled(cancelled)
        with closing(conectar_db_drive_ro(source)) as conn:
            meta=Metadata(conn)
            for stable,node in meta.nodes.items():
                parts=meta.raw_parts(stable) if allow_hidden else meta.parts(stable)
                if (is_folder is None or bool(node['is_folder']) is is_folder) and parts==expected:
                    if progress:progress('registrando')
                    return extraer_ids_proto(node['proto'])[0]
        if not announced and progress:progress('esperando_drive')
        announced=True
        if time.monotonic()>=deadline: raise TimeoutError('Drive aún no registra la carpeta. Espera un momento y vuelve a intentar la operación; la carpeta se conservará.')
        time.sleep(.6)


def wait_for_drive_manifest(profile, relative, files, directories=(), cancelled=None, progress=None, timeout=180):
    """Compare every copied path with DriveFS metadata, including hidden files."""
    source=next((p['ruta_db'] for p in detectar_perfiles_drive() if p['id']==profile),None)
    if not source:raise FileNotFoundError('Metadatos de Drive no disponibles')
    root_parts=tuple(PureWindowsPath(relative).parts)
    expected={tuple(path.parts):(False,size) for path,size in files}
    expected.update({tuple(path.parts):(True,None) for path in directories})
    deadline=time.monotonic()+timeout
    last_count=-1
    while True:
        _check_cancelled(cancelled)
        with closing(conectar_db_drive_ro(source)) as conn:
            meta=Metadata(conn)
            roots=[ident for ident,node in meta.nodes.items() if node['is_folder'] and meta.parts(ident)==root_parts]
            actual={}
            if roots:
                stack=[(roots[0],())]
                seen=set()
                while stack:
                    parent,prefix=stack.pop()
                    if parent in seen:continue
                    seen.add(parent)
                    for child in meta.children.get(parent,[]):
                        node=meta.nodes.get(child)
                        if not node or node['trashed'] or node.get('is_tombstone'):continue
                        path=prefix+(node['local_title'],)
                        folder=bool(node['is_folder'])
                        actual[path]=(folder,None if folder else node['file_size'])
                        if folder:stack.append((child,path))
            matching=sum(actual.get(path)==value for path,value in expected.items())
            if roots and matching==len(expected):return
        if progress and matching!=last_count:
            last_count=matching
            progress('esperando_drive',f'DriveFS registra {matching} de {len(expected)} elementos · sincronizando con Drive…')
        if time.monotonic()>=deadline:
            raise TimeoutError(f'Copia local completa. DriveFS registra {matching} de {len(expected)} elementos; Google Drive puede seguir sincronizando. La carpeta se conserva.')
        time.sleep(1)


def assign_items(db, profile, ids, container_id=None, name=None):
    ids=list(dict.fromkeys(ids or []))
    if not ids or len(ids)>10000: raise ValueError('Selección inválida')
    manager=ItemsManager(db)
    items=[manager.obtener(ident) for ident in ids]
    if any(item['perfil_drive']!=profile or not item['disponible'] or item['tipo']=='curso' for item in items):
        raise ValueError('Selecciona archivos visibles del perfil activo')
    library=library_root(db,profile)
    linked=bool(root_id(db,profile))
    common=normalizar(items[0]['etiquetas']) if items else []
    category=category_name(common[0]) if linked and common and all(normalizar(item['etiquetas'])[:1]==common[:1] for item in items) else INBOX if linked else 'Containers'
    containers=library/category; containers.mkdir(exist_ok=True)
    created=False
    if container_id:
        container=manager.obtener(container_id)
        if container['tipo']!='curso' or container['perfil_drive']!=profile or not container['disponible']:
            raise ValueError('Contenedor inválido')
        folder=inside(manager.ruta_local(container),library)
    else:
        folder=containers/valid_name(name)
        if folder.exists():
            if not folder.is_dir() or any(folder.iterdir()):
                raise FileExistsError('Ya existe un contenedor con ese nombre')
        else:
            created=True
    moves=[]
    targets=set()
    for item in items:
        source=inside(manager.ruta_local(item),library)
        if not source.is_file(): raise FileNotFoundError(str(source))
        target=inside(folder/source.name,library)
        if target.exists() or target.name.casefold() in targets:
            raise FileExistsError('Archivo duplicado: '+source.name)
        targets.add(target.name.casefold())
        moves.append((item,source,target))
    if not container_id:
        if created: folder.mkdir()
        relative=relative_path(db,profile,folder,library) if linked else str(PureWindowsPath(library.parent.name,'Biblioteca','Containers',folder.name))
        container_id=drive_id_for_path(profile,relative)
        with db:
            db.execute('''INSERT INTO items(drive_id,titulo,tipo,tipo_contenido,categoria_macro,ruta_relativa,perfil_drive)
                VALUES(?,?,'curso','contenedor',?, ?,?) ON CONFLICT(drive_id) DO UPDATE SET disponible=1,
                titulo=excluded.titulo,ruta_relativa=excluded.ruta_relativa,
                tipo_contenido='contenedor',formato=''
                ''',(container_id,folder.name,category,relative,profile))
            if linked and category!=INBOX:
                db.execute('UPDATE items SET etiquetas=? WHERE drive_id=?',('+'+category,container_id))
    for item,source,target in moves:
        shutil.move(str(source),str(target))
        relative=relative_path(db,profile,target,library) if linked else str(PureWindowsPath(library.parent.name,'Biblioteca',*target.relative_to(library).parts))
        with db:
            db.execute('''INSERT INTO container_entries(container_drive_id,drive_id,titulo,ruta_relativa,tamano_bytes,mime_type,perfil_drive)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(drive_id) DO UPDATE SET
                container_drive_id=excluded.container_drive_id,titulo=excluded.titulo,
                ruta_relativa=excluded.ruta_relativa,tamano_bytes=excluded.tamano_bytes,
                mime_type=excluded.mime_type,perfil_drive=excluded.perfil_drive''',
                (container_id,item['drive_id'],target.name,relative,item['tamano_bytes'],item['mime_type'],profile))
            db.execute('UPDATE items SET disponible=1,container_parent=?,ruta_relativa=? WHERE id=?',
                       (container_id,relative,item['id']))
            db.execute('''INSERT INTO pending_container_moves(drive_id,expected_relative,container_drive_id,perfil_drive)
                VALUES(?,?,?,?) ON CONFLICT(drive_id) DO UPDATE SET
                expected_relative=excluded.expected_relative,container_drive_id=excluded.container_drive_id,
                perfil_drive=excluded.perfil_drive,created_at=CURRENT_TIMESTAMP''',
                (item['drive_id'],relative,container_id,profile))
        if linked:cleanup_category(source.parent)
    return {'container_id':container_id,'moved':len(moves)}


def extract_to_library(db, profile, container, sources, remove_container=False):
    """Extract files or folders while preserving each Drive ID and nested metadata."""
    if not root_id(db,profile):raise ValueError('La extracción unificada requiere una biblioteca vinculada')
    library=library_root(db,profile)
    manager=ItemsManager(db)
    container_path=inside(manager.ruta_local(container),library)
    if container_path.parent.parent!=library:raise ValueError('El contenedor no está en una categoría')
    container_tags=normalizar(container['etiquetas'])
    plans=[];targets=set()
    for raw in sources:
        source=inside(Path(raw),container_path)
        if not source.exists() or source.is_symlink():raise FileNotFoundError(str(source))
        old=relative_path(db,profile,source,library)
        root_row=db.execute('SELECT * FROM items WHERE perfil_drive=? AND ruta_relativa=?',(profile,old)).fetchone()
        if not root_row:raise ValueError('Sin ID de Drive para el recurso extraído')
        root_item=dict(root_row)
        own=normalizar(root_item['etiquetas'])
        inherited=list(dict.fromkeys([*container_tags,*own]))
        category=container_path.parent.name
        if category.casefold()==INBOX.casefold() and inherited:
            category=category_name(inherited[0])
        elif category.casefold()!=INBOX.casefold():
            inherited=[category.casefold(),*[tag for tag in inherited if tag!=category.casefold()]]
        target=library/category/source.name
        key=str(target).casefold()
        if target.exists() or key in targets:raise FileExistsError('Ya existe un elemento en '+str(target))
        targets.add(key)
        prefix=old+'\\'
        affected=[dict(row) for row in db.execute('SELECT * FROM items WHERE perfil_drive=? AND (ruta_relativa=? OR substr(ruta_relativa,1,?)=?)',
                                                 (profile,old,len(prefix),prefix))]
        entries=[dict(row) for row in db.execute('SELECT * FROM container_entries WHERE perfil_drive=? AND (ruta_relativa=? OR substr(ruta_relativa,1,?)=?)',
                                                (profile,old,len(prefix),prefix))]
        new=relative_path(db,profile,target,library)
        plans.append((source,target,old,new,root_item,affected,entries,inherited,category))
    moved=[]
    try:
        for source,target,*_ in plans:
            target.parent.mkdir(exist_ok=True)
            shutil.move(str(source),str(target));moved.append((source,target))
        if remove_container:
            for child in container_path.iterdir():
                if child.is_file() and child.name.casefold()=='desktop.ini':child.unlink()
            container_path.rmdir()
        with db:
            for source,target,old,new,root_item,affected,entries,tags,category in plans:
                prefix=old+'\\'
                folder_id=root_item['drive_id'] if source.is_dir() or target.is_dir() else ''
                for item in affected:
                    suffix=item['ruta_relativa'][len(old):]
                    path=new+suffix
                    parent='' if item['drive_id']==root_item['drive_id'] else folder_id
                    labels=' '.join('+'+tag for tag in tags) if not parent else item['etiquetas']
                    db.execute('''UPDATE items SET ruta_relativa=?,categoria_macro=?,subcategoria='',container_parent=?,
                        etiquetas=?,disponible=1 WHERE id=?''',(path,category,parent,labels,item['id']))
                    db.execute('''INSERT INTO pending_container_moves(drive_id,expected_relative,container_drive_id,perfil_drive)
                        VALUES(?,?,?,?) ON CONFLICT(drive_id) DO UPDATE SET expected_relative=excluded.expected_relative,
                        container_drive_id=excluded.container_drive_id,perfil_drive=excluded.perfil_drive,created_at=CURRENT_TIMESTAMP''',
                        (item['drive_id'],path,parent,profile))
                for entry in entries:
                    if not folder_id:
                        db.execute('DELETE FROM container_entries WHERE id=?',(entry['id'],))
                    else:
                        path=new+entry['ruta_relativa'][len(old):]
                        db.execute('UPDATE container_entries SET container_drive_id=?,ruta_relativa=? WHERE id=?',
                                   (folder_id,path,entry['id']))
            if remove_container:
                db.execute('UPDATE items SET disponible=0 WHERE drive_id=?',(container['drive_id'],))
                db.execute('DELETE FROM container_entries WHERE container_drive_id=?',(container['drive_id'],))
                db.execute('''INSERT INTO pending_container_moves(drive_id,expected_relative,container_drive_id,perfil_drive)
                    VALUES(?,'','__removed__',?) ON CONFLICT(drive_id) DO UPDATE SET expected_relative='',
                    container_drive_id='__removed__',created_at=CURRENT_TIMESTAMP''',(container['drive_id'],profile))
        try:cleanup_category(container_path.parent)
        except OSError:logging.getLogger(__name__).exception('No se pudo limpiar la categoría vacía')
        return {'released':len(plans),'paths':[str(target) for _,target,*_ in plans]}
    except Exception:
        if remove_container and not container_path.exists():container_path.mkdir()
        for source,target in reversed(moved):
            if target.exists() and not source.exists():shutil.move(str(target),str(source))
        raise


def ungroup_container(db, profile, container_id):
    manager=ItemsManager(db); container=manager.obtener(container_id)
    if container['tipo']!='curso' or container['perfil_drive']!=profile or not container['disponible']:
        raise ValueError('Contenedor inválido')
    library=library_root(db,profile)
    linked=bool(root_id(db,profile))
    folder=inside(manager.ruta_local(container),library)
    if linked:
        if folder.parent.parent!=library:raise ValueError('Solo se pueden deshacer contenedores del nivel de categoría')
    elif folder.parent.resolve()!=(library/'Containers').resolve():
        raise ValueError('Solo se pueden deshacer contenedores de Biblioteca/Containers')
    children=list(folder.iterdir())
    if linked:
        return extract_to_library(db,profile,container,children,remove_container=True)
    for source in children:
        inside(source,library)
        if (folder.parent/source.name).exists(): raise FileExistsError('Ya existe en la categoría: '+source.name)
    entries=[dict(r) for r in db.execute('SELECT * FROM container_entries WHERE container_drive_id=?',(container_id,))]
    storage=folder.parent if linked else library/'Storage'
    for source in children:
        destination=folder.parent/source.name if linked else library/source.name
        if not linked and classify_file(source.name,allow_other=True)=='archivo':
            storage.mkdir(exist_ok=True);destination=storage/source.name
        shutil.move(str(source),str(destination))
    folder.rmdir()
    with db:
        db.execute('DELETE FROM container_entries WHERE container_drive_id=?',(container_id,))
        db.execute('UPDATE items SET disponible=0 WHERE drive_id=?',(container_id,))
        db.execute('DELETE FROM pending_container_moves WHERE container_drive_id=?',(container_id,))
        db.execute('''INSERT INTO pending_container_moves(drive_id,expected_relative,container_drive_id,perfil_drive)
            VALUES(?,'','__removed__',?) ON CONFLICT(drive_id) DO UPDATE SET
            expected_relative='',container_drive_id='__removed__',created_at=CURRENT_TIMESTAMP''',(container_id,profile))
        for entry in entries:
            old=PureWindowsPath(entry['ruta_relativa'])
            parts=old.parts
            container_index=next((i for i,part in enumerate(parts) if part.casefold()=='containers'),None)
            tail=parts[container_index+2:] if container_index is not None else (entry['titulo'],)
            if not tail: continue
            ext=Path(entry['titulo']).suffix.lower()
            tipo=classify_file(entry['titulo'],allow_other=True)
            if not tipo: continue
            title,author=clean_book_title_and_author(entry['titulo'],tipo) if tipo=='pdf' else (Path(entry['titulo']).stem,'')
            target_parts=(folder.parent.name,entry['titulo']) if linked else ('Storage',entry['titulo']) if tipo=='archivo' else (entry['titulo'],)
            relative=relative_path(db,profile,library.joinpath(*target_parts),library) if linked else str(PureWindowsPath(library.parent.name,'Biblioteca',*target_parts))
            db.execute('''INSERT INTO items(drive_id,titulo,autor,tipo,tipo_contenido,formato,ruta_relativa,perfil_drive,tamano_bytes,mime_type)
                VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(drive_id) DO UPDATE SET
                ruta_relativa=excluded.ruta_relativa,tipo=excluded.tipo,tipo_contenido=excluded.tipo_contenido,
                formato=excluded.formato,disponible=1,container_parent='' ''',
                (entry['drive_id'],title,author,tipo,'documento' if tipo=='pdf' else 'otro' if tipo=='archivo' else tipo,
                 ext.lstrip('.').upper(),relative,profile,entry['tamano_bytes'],entry['mime_type']))
            db.execute('''INSERT INTO pending_container_moves(drive_id,expected_relative,container_drive_id,perfil_drive)
                VALUES(?,?,'',?) ON CONFLICT(drive_id) DO UPDATE SET
                expected_relative=excluded.expected_relative,container_drive_id='',created_at=CURRENT_TIMESTAMP''',
                (entry['drive_id'],relative,profile))
    return {'released':len(children)}


def import_container_folder(db, profile, source_path, progress=None, cancelled=None, on_target=None, active_tag=None):
    source=Path(source_path).resolve()
    if not source.is_dir() or source.is_symlink(): raise ValueError('Selecciona una carpeta válida')
    library=library_root(db,profile)
    linked=bool(root_id(db,profile));category=category_name(active_tag) if linked and active_tag else INBOX if linked else 'Containers'
    containers=library/category; containers.mkdir(exist_ok=True)
    target=containers/valid_name(source.name)
    if target.exists() or target.resolve().is_relative_to(source):
        raise FileExistsError('El contenedor ya existe o la carpeta está dentro de sí misma')
    manifest,directories=_manifest(source,cancelled)
    target.mkdir()
    if on_target:on_target(str(target),'folder')
    stats={'files_done':0,'files_total':len(manifest),'bytes_current':0,'bytes_total':sum(size for _,size in manifest)}
    label=f'Copiando “{source.name}” a {category}'
    if progress:progress('copiando',f'{label} · aprox. 10%')
    _copy_tree(source,target,cancelled,progress,stats,label,create_root=False)
    _verify_copy(source,target,manifest,directories,cancelled)
    _check_cancelled(cancelled)
    return {'title':target.name,'kind':'folder','file_count':len(manifest),'folder_count':len(directories),'total_bytes':sum(size for _,size in manifest)}

def import_library_file(db, profile, source_path, progress=None, cancelled=None, on_target=None, thumbnail_dir=None, active_tag=None):
    source=Path(source_path).resolve()
    if not source.is_file() or source.is_symlink():raise ValueError('Selecciona un archivo válido')
    library=library_root(db,profile)
    linked=bool(root_id(db,profile));category=category_name(active_tag) if linked and active_tag else INBOX if linked else 'Storage'
    storage=library/category;storage.mkdir(exist_ok=True)
    filename=valid_name(source.name)
    target=storage/filename
    if target.exists():raise FileExistsError('Ya existe un archivo con ese nombre en Storage')
    with target.open('xb'):pass
    if on_target:on_target(str(target),'file')
    stats={'files_done':0,'files_total':1,'bytes_current':0,'bytes_total':source.stat().st_size}
    label=f'Copiando “{filename}” a {category}'
    if progress:progress('copiando',f'{label} · aprox. 10%')
    _copy_file(source,target,cancelled,progress,stats,label)
    _check_cancelled(cancelled)
    if not target.is_file() or target.stat().st_size!=source.stat().st_size:
        raise IOError(f'No se pudo verificar la copia del archivo “{filename}”')
    _check_cancelled(cancelled)
    if thumbnail_dir:
        try:
            from .thumbnailer import create_thumbnail, thumbnail_name
            relative=relative_path(db,profile,target,library) if linked else str(PureWindowsPath(library.parent.name,'Biblioteca','Storage',target.name))
            create_thumbnail(target,Path(thumbnail_dir)/thumbnail_name(profile,relative))
        except Exception:
            logging.getLogger(__name__).exception('No se pudo generar la miniatura para %s',filename)
    tipo=classify_file(filename,allow_other=True)
    return {'title':Path(filename).stem,'kind':'file','type':tipo,'size':target.stat().st_size}
