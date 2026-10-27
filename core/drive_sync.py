"""Lectura de metadatos DriveFS. Nunca abre contenido de la unidad montada."""
import ctypes
import json
import logging
import os
import shutil
from pathlib import Path, PureWindowsPath
import re
import sqlite3
from .database import configurar, preferencia
from .cleaner import clean_book_title_and_author

ID_PATTERN=re.compile(r"[A-Za-z0-9_-]{10,200}\Z")
class SeleccionRequerida(ValueError): pass

def conectar_db_drive_ro(ruta_db):
    db=sqlite3.connect(Path(ruta_db).resolve().as_uri()+'?mode=ro',uri=True,timeout=10)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    return db

def extraer_ids_proto(blob):
    """Decodifica wire protobuf; campos 1=file ID, 2=parent ID repetible."""
    blob=bytes(blob or b''); pos=0; found={1:[],2:[]}
    def varint():
        nonlocal pos
        result=0
        for shift in range(0,70,7):
            if pos>=len(blob): raise ValueError('Protobuf truncado')
            b=blob[pos]; pos+=1; result|=(b&127)<<shift
            if not b&128: return result
        raise ValueError('Varint inválido')
    while pos<len(blob):
        key=varint(); field,wire=key>>3,key&7
        if not field: raise ValueError('Campo protobuf inválido')
        if wire==0: varint(); continue
        if wire==1: size=8
        elif wire==5: size=4
        elif wire==2: size=varint()
        else: raise ValueError('Wire type no soportado')
        end=pos+size
        if end>len(blob): raise ValueError('Protobuf truncado')
        if wire==2 and field in found:
            value=blob[pos:end].decode('ascii')
            if not ID_PATTERN.fullmatch(value): raise ValueError('Drive ID inválido')
            found[field].append(value)
        pos=end
    if len(found[1])!=1: raise ValueError('File ID ausente o ambiguo')
    return found[1][0],found[2]

def excluido(name):
    return not name or name.startswith('.') or 'balisco_backup' in name.casefold() or any(c in name for c in ('/', '\\', ':')) or name in ('.','..')

class Metadata:
    def __init__(self, db):
        columns={r[1] for r in db.execute('PRAGMA table_info(items)')}
        required={'stable_id','local_title','is_folder','mime_type','file_size','trashed','proto'}
        if not required<=columns: raise ValueError('Esquema DriveFS no compatible')
        fields=','.join(sorted(required-{'proto'}))+',CAST(proto AS BLOB) AS proto'
        if 'is_tombstone' in columns: fields+=',is_tombstone'
        self.nodes={r['stable_id']:dict(r) for r in db.execute('SELECT '+fields+' FROM items')}
        self.parents={}; self.children={}; self.cache={}; self.raw_cache={}
        for child,parent in db.execute('SELECT item_stable_id,parent_stable_id FROM stable_parents ORDER BY parent_stable_id'):
            self.parents.setdefault(child,[]).append(parent)
            self.children.setdefault(parent,[]).append(child)
    def parts(self, ident, seen=None):
        if ident in self.cache: return self.cache[ident]
        seen=set() if seen is None else seen
        if ident in seen: return None
        node=self.nodes.get(ident)
        if not node or node['trashed'] or node.get('is_tombstone') or excluido(node['local_title']): return None
        name=node['local_title']
        if name in ('Mi unidad','My Drive'): result=(name,)
        else:
            result=None
            for parent in self.parents.get(ident,[]):
                base=self.parts(parent,seen|{ident})
                if base: result=base+(name,); break
        self.cache[ident]=result
        return result
    def raw_parts(self, ident, seen=None):
        """Resolve an internal Drive path, including Balisco's hidden metadata folder."""
        if ident in self.raw_cache:return self.raw_cache[ident]
        seen=set() if seen is None else seen
        if ident in seen:return None
        node=self.nodes.get(ident)
        if not node or node['trashed'] or node.get('is_tombstone'):return None
        name=node['local_title']
        if name in ('Mi unidad','My Drive'):
            self.raw_cache[ident]=(name,)
            return (name,)
        for parent in self.parents.get(ident,[]):
            base=self.raw_parts(parent,seen|{ident})
            if base:
                self.raw_cache[ident]=base+(name,)
                return self.raw_cache[ident]
        return None
    def roots(self, name='Biblioteca'):
        return [i for i,n in self.nodes.items() if n['is_folder'] and n['local_title']==name and self.parts(i) and len(self.parts(i))==2]

def reconstruir_ruta_desde_parents(stable_id,cursor):
    parts=Metadata(cursor.connection).parts(stable_id)
    return str(PureWindowsPath(*parts)) if parts else ''

def detectar_perfiles_drive(base=None):
    base=Path(base) if base else Path(os.environ.get('LOCALAPPDATA',''))/'Google'/'DriveFS'
    result=[]
    for path in sorted(base.glob('*/metadata_sqlite_db')):
        try:
            db=conectar_db_drive_ro(path)
            try: roots=Metadata(db).roots()
            finally: db.close()
            result.append(dict(id=path.parent.name,ruta_db=str(path),tiene_biblioteca=bool(roots),raices=roots))
        except (sqlite3.Error,ValueError) as exc:
            result.append(dict(id=path.parent.name,ruta_db=str(path),tiene_biblioteca=False,error=str(exc)))
    return result

def obtener_o_seleccionar_perfil_activo(conexion_db, perfiles=None):
    perfiles=detectar_perfiles_drive() if perfiles is None else perfiles
    valid=[p for p in perfiles if not p.get('error')]
    selected=preferencia(conexion_db,'id_perfil_drive')
    if selected and any(p['id']==selected for p in valid): return selected
    if len(valid)!=1: raise SeleccionRequerida('Selecciona un perfil con Biblioteca: '+', '.join(p['id'] for p in valid))
    with conexion_db: configurar(conexion_db,'id_perfil_drive',valid[0]['id'])
    return valid[0]['id']

def cambiar_perfil_activo(nuevo_id_perfil,conexion_db):
    if not any(p['id']==nuevo_id_perfil and not p.get('error') for p in detectar_perfiles_drive()): raise ValueError('Perfil no disponible')
    with conexion_db: configurar(conexion_db,'id_perfil_drive',nuevo_id_perfil)
    return True

def obtener_letra_drive():
    if os.name!='nt': raise FileNotFoundError('Drive montado requiere Windows')
    mask=ctypes.windll.kernel32.GetLogicalDrives(); matches=[]
    for n in range(26):
        if mask & (1<<n):
            root=Path(chr(65+n)+':/');
            if any((root/name/'Biblioteca').is_dir() for name in ('Mi unidad','My Drive')): matches.append(str(root))
    if len(matches)!=1: raise SeleccionRequerida('Unidad ausente o ambigua; configura unidad_drive para el perfil activo')
    return matches[0]

MEDIA_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.wmv', '.m4v', '.mpeg', '.mpg', '.3gp', '.3g2', '.ts', '.m2ts', '.mts', '.vob', '.ogv', '.asf'}
BOOK_EXTENSIONS = {'.pdf', '.epub', '.azw', '.azw3', '.mobi', '.kfx', '.fb2', '.djvu', '.djv', '.cbz', '.cbr', '.cb7', '.lit', '.pdb', '.txt', '.rtf', '.lrf', '.kepub'}
AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.aac', '.flac', '.wav', '.ogg', '.oga', '.opus', '.wma', '.aiff', '.aif', '.alac', '.ape', '.amr', '.mid', '.midi', '.m4b'}
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.tif', '.tiff', '.heic', '.heif', '.avif', '.svg', '.ico', '.jxl', '.jp2', '.j2k', '.apng', '.raw', '.dng', '.cr2', '.nef', '.arw'}

def classify_file(name, allow_other=False):
    ext=Path(name).suffix.casefold()
    if ext in BOOK_EXTENSIONS:return 'pdf'
    if ext in MEDIA_EXTENSIONS:return 'video'
    if ext in AUDIO_EXTENSIONS:return 'audio'
    if ext in IMAGE_EXTENSIONS:return 'imagen'
    return 'archivo' if allow_other else None

class DriveSync:
    def __init__(self,db): self.db=db
    def _local_file_exists(self,perfil,relative):
        path=PureWindowsPath(relative)
        if not relative or path.is_absolute() or path.drive or '..' in path.parts:
            return False
        root=preferencia(self.db,'unidad_drive:'+perfil)
        if not root:
            try:
                from .library_layout import root_id, mounted_drive
                root=mounted_drive(self.db,perfil) if root_id(self.db,perfil) else obtener_letra_drive()
            except (FileNotFoundError,SeleccionRequerida): return False
        return Path(root).joinpath(*path.parts).is_file()

    def _pdf_replacements(self, rows, perfil, meta):
        """Relink unambiguous uploads by path, then by size, format and clean title."""
        incoming_ids={row[0] for row in rows}
        known={item['drive_id']:item for item in self.db.execute('''SELECT drive_id,perfil_drive,tipo,
            notas,descripcion,etiquetas,rating,es_favorito,titulo_personalizado,fijado,
            indexar_contenido,oculto,ultimo_acceso,recent_hidden,estado_lectura,search_override FROM items''')}
        removed={row['drive_id'] for row in self.db.execute('''SELECT drive_id FROM pending_container_moves
            WHERE perfil_drive=? AND container_drive_id='__removed__' ''',(perfil,))}
        old_by_path={}
        old_items=list(self.db.execute('SELECT id,drive_id,ruta_relativa,tipo,tamano_bytes,formato FROM items WHERE perfil_drive=?',(perfil,)))
        for item in old_items:
            if item['drive_id'] not in incoming_ids:
                old_by_path.setdefault(item['ruta_relativa'],[]).append(item)
        new_by_path={}
        for row in rows:
            existing=known.get(row[0])
            pristine=not existing or (existing['perfil_drive']==perfil and existing['tipo']==row[3] and
                not any((existing['notas'],existing['descripcion'],existing['etiquetas'],existing['rating'],
                         existing['es_favorito'],existing['titulo_personalizado'],existing['fijado'],
                         existing['indexar_contenido'],existing['oculto'],existing['ultimo_acceso'],
                         existing['recent_hidden'])) and existing['estado_lectura']=='pendiente' and
                existing['search_override']==-1)
            if row[3]!='curso' and pristine:
                new_by_path.setdefault(row[6],[]).append(row)
        candidates=[(old_by_path[path][0], new_rows[0])
                    for path,new_rows in new_by_path.items()
                    if len(new_rows)==1 and len(old_by_path.get(path,()))==1 and old_by_path[path][0]['tipo']==new_rows[0][3]]
        matched_old={old['drive_id'] for old,_ in candidates}
        matched_new={new[0] for _,new in candidates}
        def signature(title,size,fmt,kind):
            return (int(size or 0),str(fmt or '').casefold(),re.sub(r'\s+',' ',title).strip().casefold(),kind)
        old_by_fingerprint={}
        for item in old_items:
            if item['drive_id'] in incoming_ids or item['drive_id'] in matched_old or item['tipo']=='curso':continue
            filename=PureWindowsPath(item['ruta_relativa']).name
            cleaned,_=clean_book_title_and_author(filename,item['tipo']) if item['tipo']=='pdf' else (Path(filename).stem,'')
            key=signature(cleaned,item['tamano_bytes'],item['formato'],item['tipo'])
            old_by_fingerprint.setdefault(key,[]).append(item)
        new_by_fingerprint={}
        for incoming in rows:
            if incoming[0] in matched_new or incoming[3]=='curso':continue
            if old_by_path.get(incoming[6]):continue
            if incoming not in new_by_path.get(incoming[6],()):continue
            key=signature(incoming[1],incoming[8],incoming[12],incoming[3])
            new_by_fingerprint.setdefault(key,[]).append(incoming)
        candidates.extend((old_by_fingerprint[key][0],new_rows[0])
                          for key,new_rows in new_by_fingerprint.items()
                          if len(new_rows)==1 and len(old_by_fingerprint.get(key,()))==1)
        unresolved={old['drive_id'] for old,_ in candidates if old['drive_id'] not in removed}
        live_ids=set()
        if unresolved:
            for node in meta.nodes.values():
                if not unresolved: break
                if node['trashed'] or node.get('is_tombstone'): continue
                try: ident=extraer_ids_proto(node['proto'])[0]
                except (ValueError,UnicodeError): continue
                if ident in unresolved:
                    unresolved.remove(ident)
                    live_ids.add(ident)
        return [(old,new) for old,new in candidates if old['drive_id'] not in live_ids]

    def sincronizar_biblioteca(self,ruta_raiz='Biblioteca',ruta_db=None,perfil=None,cancel_check=None):
        check_cancelled=cancel_check or (lambda:None)
        check_cancelled()
        if ruta_db is None:
            profiles=detectar_perfiles_drive(); perfil=perfil or obtener_o_seleccionar_perfil_activo(self.db,profiles)
            ruta_db=next(p['ruta_db'] for p in profiles if p['id']==perfil)
        perfil=perfil or Path(ruta_db).parent.name
        source=conectar_db_drive_ro(ruta_db)
        try:
            source.execute('BEGIN'); meta=Metadata(source)
        finally: source.close()
        check_cancelled()
        from .library_layout import root_id, root_parts, RESERVED, INBOX, mounted_drive
        linked=root_id(self.db,perfil)
        if linked:
            if preferencia(self.db,'migration_pending:'+perfil)=='1':
                raise SeleccionRequerida('La biblioteca antigua requiere migración antes de sincronizar')
            root,base_parts=root_parts(meta,linked)
            if root is None:
                with self.db:
                    self.db.execute('DELETE FROM configuracion WHERE clave=?',('biblioteca_root_id:'+perfil,))
                    self.db.execute('UPDATE items SET disponible=0 WHERE perfil_drive=?',(perfil,))
                raise SeleccionRequerida('La carpeta vinculada fue eliminada; selecciona otra ubicación')
            try:
                if not mounted_drive(self.db,perfil).joinpath(*base_parts).is_dir():
                    raise FileNotFoundError('La carpeta vinculada aún no está disponible en Drive')
            except (FileNotFoundError,ValueError): raise
            legacy=False
        else:
            roots=meta.roots(ruta_raiz)
            if len(roots)!=1: raise SeleccionRequerida('Selecciona la ubicación de tu biblioteca')
            root=roots[0];base_parts=meta.parts(root);legacy=True
        root_depth=len(base_parts)
        rows=[]; entries=[]; skipped=0; visited=set();container_roots={};internal_ids={};physical_categories={}

        subtree_bytes={}; computing=set()
        def compute_size(ident):
            check_cancelled()
            if ident in subtree_bytes: return subtree_bytes[ident]
            if ident in computing: return 0
            computing.add(ident)
            node=meta.nodes.get(ident)
            size=(node['file_size'] or 0) if node else 0
            if node and node['is_folder']:
                size+=sum(compute_size(cid) for cid in meta.children.get(ident,[])
                          if cid in meta.nodes and meta.parts(cid))
            computing.remove(ident)
            subtree_bytes[ident]=size
            return size

        compute_size(root)

        def visit(ident, container_id=None):
            nonlocal skipped
            check_cancelled()
            if ident in visited: return
            visited.add(ident)
            node=meta.nodes[ident]; parts=meta.parts(ident)
            if not parts: return
            try: drive_id,_=extraer_ids_proto(node['proto'])
            except (ValueError,UnicodeError): skipped+=1; return

            relative=parts[root_depth:]
            if not legacy and relative and relative[0].casefold() in RESERVED and relative[0].casefold()!=INBOX.casefold(): return
            if node['is_folder']:
                in_containers=(len(relative)==2 if not legacy else len(parts)==4 and parts[2].casefold()=='containers')
                if container_id is not None:
                    internal_ids[drive_id]=container_id
                    rows.append((drive_id,node['local_title'],'','curso',relative[0] if not legacy else 'Containers','',str(PureWindowsPath(*parts)),
                                 'portadas/'+drive_id+'.jpg',subtree_bytes.get(ident,0),node['mime_type'],perfil,'contenedor',''))
                if container_id is None and in_containers:
                    categories=relative[:-1] if not legacy else parts[2:-1]
                    cat_macro=categories[0] if categories else 'General'
                    subcat=' / '.join(categories[1:])
                    c_title, c_author = clean_book_title_and_author(node['local_title'], 'curso')
                    rows.append((
                        drive_id,
                        c_title,
                        c_author,
                        'curso',
                        cat_macro,
                        subcat,
                        str(PureWindowsPath(*parts)),
                        'portadas/'+drive_id+'.jpg',
                        subtree_bytes.get(ident,0),
                        node['mime_type'],
                        perfil,
                        'contenedor',
                        '',
                    ))
                    container_roots[drive_id]=parts
                    container_id=drive_id
                    if not legacy: physical_categories[drive_id]=cat_macro
                for cid in meta.children.get(ident,[]):
                    if cid in meta.nodes and meta.parts(cid):
                        visit(cid,container_id)
                return

            if container_id:
                internal_ids[drive_id]=container_id
                root_parts=container_roots.get(container_id,())
                relative_parts=parts[len(root_parts):] if parts[:len(root_parts)]==root_parts else (node['local_title'],)
                entries.append((container_id,drive_id,'/'.join(relative_parts),
                                str(PureWindowsPath(*parts)),node['file_size'] or 0,
                                node['mime_type'],perfil))
                ext=Path(node['local_title']).suffix.lower()
                tipo=classify_file(node['local_title'],allow_other=True) or 'archivo'
                title,author=clean_book_title_and_author(node['local_title'],tipo) if tipo=='pdf' else (Path(node['local_title']).stem,'')
                rows.append((drive_id,title,author,tipo,relative[0] if not legacy else 'Containers','',str(PureWindowsPath(*parts)),
                             'portadas/'+drive_id+'.jpg',node['file_size'] or 0,node['mime_type'],perfil,
                             'documento' if tipo=='pdf' else 'otro' if tipo=='archivo' else tipo,ext.lstrip('.').upper()))
                return

            ext=Path(node['local_title']).suffix.lower()
            if not legacy and len(relative)!=2: return
            in_storage=legacy and len(parts)>=4 and parts[2].casefold()=='storage'
            archive_in_containers=legacy and len(parts)==4 and parts[2].casefold()=='containers' and ext in {'.zip','.rar'}
            tipo=classify_file(node['local_title'],allow_other=not legacy or in_storage or archive_in_containers)
            if tipo is None: return
            categories=relative[:-1] if not legacy else parts[2:-1]
            cat_macro=categories[0] if categories else 'General'
            subcat=' / '.join(categories[1:])
            c_title, c_author = clean_book_title_and_author(node['local_title'], tipo) if tipo=='pdf' else (Path(node['local_title']).stem,'')
            rows.append((
                drive_id,
                c_title,
                c_author,
                tipo,
                cat_macro,
                subcat,
                str(PureWindowsPath(*parts)),
                'portadas/'+drive_id+'.jpg',
                node['file_size'] or 0,
                node['mime_type'],
                perfil,
                'contenedor' if archive_in_containers else 'documento' if tipo=='pdf' else 'otro' if tipo=='archivo' else tipo,
                ext.lstrip('.').upper(),
            ))
            if not legacy: physical_categories[drive_id]=cat_macro

        for child in meta.children.get(root,[]):
            check_cancelled();visit(child)
        pending=list(self.db.execute("SELECT * FROM pending_container_moves WHERE perfil_drive=? AND created_at>=datetime('now','-1 day')",(perfil,)))
        observed={row[0]:row[6] for row in rows}
        observed.update({entry[1]:entry[3] for entry in entries})
        resolved=[]
        for move in pending:
            check_cancelled()
            ident=move['drive_id']; expected=move['expected_relative']; target=move['container_drive_id']
            if (target=='__removed__' and ident not in observed) or (target!='__removed__' and observed.get(ident,'').casefold()==expected.casefold()):
                resolved.append(ident); continue
            if (target=='__removed__' and expected and observed.get(ident)==expected and
                sum(path==expected for path in observed.values())==1 and
                self._local_file_exists(perfil,expected)):
                resolved.append(ident); continue
            rows=[row for row in rows if row[0]!=ident]
            entries=[entry for entry in entries if entry[1]!=ident]
            if target=='__removed__':
                entries=[entry for entry in entries if entry[0]!=ident]
            else:
                old=self.db.execute('''SELECT drive_id,titulo,autor,tipo,categoria_macro,subcategoria,ruta_relativa,
                    ruta_portada,tamano_bytes,mime_type,perfil_drive,tipo_contenido,formato FROM items WHERE drive_id=? AND disponible=1''',(ident,)).fetchone()
                if old: rows.append(tuple(old))
                if target:
                    old=self.db.execute('SELECT container_drive_id,drive_id,titulo,ruta_relativa,tamano_bytes,mime_type,perfil_drive FROM container_entries WHERE drive_id=?',(ident,)).fetchone()
                    if old: entries.append(tuple(old))
        pending_unresolved={move['drive_id'] for move in pending if move['drive_id'] not in resolved}
        cleanup_dirs=set()
        if not legacy:
            drive_path=mounted_drive(self.db,perfil)
            library_path=drive_path.joinpath(*base_parts).resolve()
            for row in rows:
                if row[0] not in physical_categories:continue
                old=self.db.execute('SELECT ruta_relativa FROM items WHERE drive_id=? AND perfil_drive=?',(row[0],perfil)).fetchone()
                if old and old['ruta_relativa']!=row[6]:
                    prior=drive_path.joinpath(*PureWindowsPath(old['ruta_relativa']).parts).resolve().parent
                    if prior.parent==library_path:cleanup_dirs.add(prior)
        check_cancelled()
        replacements=[] if skipped else self._pdf_replacements(rows,perfil,meta)
        with self.db:
            check_cancelled()
            self.db.execute("DELETE FROM pending_container_moves WHERE perfil_drive=? AND created_at<datetime('now','-1 day')",(perfil,))
            self.db.executemany('DELETE FROM pending_container_moves WHERE drive_id=?',[(ident,) for ident in resolved])
            for old,new in replacements:
                self.db.execute('DELETE FROM container_entries WHERE drive_id=? AND perfil_drive=?',
                                (new[0],perfil))
                self.db.execute('DELETE FROM items WHERE drive_id=? AND perfil_drive=?',
                                (new[0],perfil))
                self.db.execute('UPDATE items SET drive_id=?,ruta_portada=? WHERE id=?',
                                (new[0],new[7],old['id']))
                self.db.execute('UPDATE container_entries SET drive_id=? WHERE drive_id=? AND perfil_drive=?',
                                (new[0],old['drive_id'],perfil))
                self.db.execute('DELETE FROM pending_container_moves WHERE drive_id=?',(old['drive_id'],))
            if not skipped:
                self.db.execute('CREATE TEMP TABLE IF NOT EXISTS sync_items_seen(drive_id TEXT PRIMARY KEY) WITHOUT ROWID')
                self.db.execute('DELETE FROM sync_items_seen')
                self.db.executemany('INSERT OR IGNORE INTO sync_items_seen(drive_id) VALUES(?)',[(row[0],) for row in rows])
                self.db.execute('''UPDATE items SET disponible=0 WHERE perfil_drive=? AND disponible=1
                    AND NOT EXISTS(SELECT 1 FROM sync_items_seen s WHERE s.drive_id=items.drive_id)''',(perfil,))
            self.db.executemany("""INSERT INTO items(drive_id,titulo,autor,tipo,categoria_macro,subcategoria,ruta_relativa,ruta_portada,tamano_bytes,mime_type,perfil_drive,tipo_contenido,formato)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(drive_id) DO UPDATE SET
              titulo=CASE WHEN items.titulo_personalizado=1 THEN items.titulo ELSE excluded.titulo END,
              autor=CASE WHEN items.autor != '' THEN items.autor ELSE excluded.autor END,
              tipo=excluded.tipo,tipo_contenido=excluded.tipo_contenido,formato=excluded.formato,categoria_macro=excluded.categoria_macro,subcategoria=excluded.subcategoria,
              ruta_relativa=excluded.ruta_relativa,ruta_portada=excluded.ruta_portada,tamano_bytes=excluded.tamano_bytes,
              mime_type=excluded.mime_type,perfil_drive=excluded.perfil_drive,
              disponible=1 WHERE items.disponible!=1 OR
              (items.titulo_personalizado=0 AND items.titulo IS NOT excluded.titulo) OR
              (items.autor='' AND items.autor IS NOT excluded.autor) OR
              items.tipo IS NOT excluded.tipo OR items.tipo_contenido IS NOT excluded.tipo_contenido OR
              items.formato IS NOT excluded.formato OR items.categoria_macro IS NOT excluded.categoria_macro OR
              items.subcategoria IS NOT excluded.subcategoria OR items.ruta_relativa IS NOT excluded.ruta_relativa OR
              items.ruta_portada IS NOT excluded.ruta_portada OR items.tamano_bytes IS NOT excluded.tamano_bytes OR
              items.mime_type IS NOT excluded.mime_type OR items.perfil_drive IS NOT excluded.perfil_drive""",rows)
            if not legacy:
                from .tags_manager import normalizar
                for ident,category in physical_categories.items():
                    if ident in pending_unresolved:continue
                    item=self.db.execute('SELECT id,etiquetas FROM items WHERE drive_id=? AND perfil_drive=?',(ident,perfil)).fetchone()
                    if not item: continue
                    tags=normalizar(item['etiquetas'])
                    if category.casefold()==INBOX.casefold(): updated=[]
                    else:
                        primary=category.casefold()
                        updated=[primary,*[tag for tag in tags if tag!=primary]]
                    value=' '.join('+'+tag for tag in updated)
                    if value!=item['etiquetas']:
                        self.db.execute('UPDATE items SET etiquetas=? WHERE id=?',(value,item['id']))
            self.db.executemany('UPDATE items SET container_parent=? WHERE drive_id=? AND perfil_drive=? AND container_parent IS NOT ?',
                                [(parent,ident,perfil,parent) for ident,parent in internal_ids.items() if ident not in pending_unresolved])
            self.db.executemany("UPDATE items SET container_parent='' WHERE drive_id=? AND perfil_drive=? AND container_parent!=''",
                                [(row[0],perfil) for row in rows if row[0] not in internal_ids and row[0] not in pending_unresolved])
            check_cancelled()
            if not skipped:
                self.db.execute('CREATE TEMP TABLE IF NOT EXISTS sync_entries_seen(drive_id TEXT PRIMARY KEY) WITHOUT ROWID')
                self.db.execute('DELETE FROM sync_entries_seen')
                self.db.executemany('INSERT OR IGNORE INTO sync_entries_seen(drive_id) VALUES(?)',[(entry[1],) for entry in entries])
                self.db.execute('''DELETE FROM container_entries WHERE perfil_drive=? AND
                    NOT EXISTS(SELECT 1 FROM sync_entries_seen s WHERE s.drive_id=container_entries.drive_id)''',(perfil,))
            self.db.executemany('''INSERT INTO container_entries(container_drive_id,drive_id,titulo,ruta_relativa,tamano_bytes,mime_type,perfil_drive)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(drive_id) DO UPDATE SET
                container_drive_id=excluded.container_drive_id,titulo=excluded.titulo,
                ruta_relativa=excluded.ruta_relativa,tamano_bytes=excluded.tamano_bytes,
                mime_type=excluded.mime_type,perfil_drive=excluded.perfil_drive WHERE
                container_entries.container_drive_id IS NOT excluded.container_drive_id OR
                container_entries.titulo IS NOT excluded.titulo OR
                container_entries.ruta_relativa IS NOT excluded.ruta_relativa OR
                container_entries.tamano_bytes IS NOT excluded.tamano_bytes OR
                container_entries.mime_type IS NOT excluded.mime_type OR
                container_entries.perfil_drive IS NOT excluded.perfil_drive''',entries)
            check_cancelled()
            configurar(self.db,'id_perfil_drive',perfil)
        if replacements:
            db_file=self.db.execute('PRAGMA database_list').fetchone()[2]
            if db_file:
                covers=Path(db_file).parent/'portadas'
                for old,new in replacements:
                    source=covers/(old['drive_id']+'.jpg')
                    target=covers/(new[0]+'.jpg')
                    if source.is_file() and not source.is_symlink() and not target.exists():
                        try: shutil.copy2(source,target)
                        except OSError: logging.getLogger(__name__).exception('No se pudo conservar la portada de %s',old['drive_id'])
        if not legacy:
            from .library_layout import cleanup_category
            for folder in cleanup_dirs:
                try:cleanup_category(folder)
                except OSError:logging.getLogger(__name__).exception('No se pudo limpiar %s',folder)
        return dict(indexados=len(rows),omitidos_proto=skipped,perfil=perfil,revinculados=len(replacements))
    def exportar_libros(self,destino):
        rows=[dict(r) for r in self.db.execute("SELECT drive_id,titulo,ruta_relativa FROM items WHERE tipo='pdf' AND disponible=1 AND perfil_drive=?",(preferencia(self.db,'id_perfil_drive',''),))]
        Path(destino).write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
        return len(rows)
