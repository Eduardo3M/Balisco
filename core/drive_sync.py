"""Lectura de metadatos DriveFS. Nunca abre contenido de la unidad montada."""
import ctypes
import json
import os
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
        self.parents={}; self.children={}; self.cache={}
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
    valid=[p for p in perfiles if p['tiene_biblioteca']]
    selected=preferencia(conexion_db,'id_perfil_drive')
    if selected and any(p['id']==selected for p in valid): return selected
    if len(valid)!=1: raise SeleccionRequerida('Selecciona un perfil con Biblioteca: '+', '.join(p['id'] for p in valid))
    with conexion_db: configurar(conexion_db,'id_perfil_drive',valid[0]['id'])
    return valid[0]['id']

def cambiar_perfil_activo(nuevo_id_perfil,conexion_db):
    if not any(p['id']==nuevo_id_perfil and p['tiene_biblioteca'] for p in detectar_perfiles_drive()): raise ValueError('Perfil no disponible')
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
        roots=meta.roots(ruta_raiz)
        if len(roots)!=1: raise SeleccionRequerida('Biblioteca raíz ausente o ambigua; no se modifica el catálogo')
        root=roots[0]; rows=[]; entries=[]; skipped=0; visited=set()

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

            if node['is_folder']:
                in_containers=len(parts)==4 and parts[2].casefold()=='containers'
                if container_id is None and in_containers:
                    categories=parts[2:-1]
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
                    container_id=drive_id
                for cid in meta.children.get(ident,[]):
                    if cid in meta.nodes and meta.parts(cid):
                        visit(cid,container_id)
                return

            if container_id:
                entries.append((container_id,drive_id,node['local_title'],
                                str(PureWindowsPath(*parts)),node['file_size'] or 0,
                                node['mime_type'],perfil))
                return

            ext=Path(node['local_title']).suffix.lower()
            in_storage=len(parts)>=4 and parts[2].casefold()=='storage'
            archive_in_containers=len(parts)==4 and parts[2].casefold()=='containers' and ext in {'.zip','.rar'}
            tipo=classify_file(node['local_title'],allow_other=in_storage or archive_in_containers)
            if tipo is None: return
            categories=parts[2:-1]
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
            rows=[row for row in rows if row[0]!=ident]
            entries=[entry for entry in entries if entry[1]!=ident]
            if target=='__removed__':
                entries=[entry for entry in entries if entry[0]!=ident]
            elif target:
                old=self.db.execute('SELECT container_drive_id,drive_id,titulo,ruta_relativa,tamano_bytes,mime_type,perfil_drive FROM container_entries WHERE drive_id=?',(ident,)).fetchone()
                if old: entries.append(tuple(old))
            else:
                old=self.db.execute('''SELECT drive_id,titulo,autor,tipo,categoria_macro,subcategoria,ruta_relativa,
                    ruta_portada,tamano_bytes,mime_type,perfil_drive,tipo_contenido,formato FROM items WHERE drive_id=?''',(ident,)).fetchone()
                if old: rows.append(tuple(old))
        check_cancelled()
        with self.db:
            check_cancelled()
            self.db.execute("DELETE FROM pending_container_moves WHERE perfil_drive=? AND created_at<datetime('now','-1 day')",(perfil,))
            self.db.executemany('DELETE FROM pending_container_moves WHERE drive_id=?',[(ident,) for ident in resolved])
            if not skipped: self.db.execute('UPDATE items SET disponible=0 WHERE perfil_drive=?',(perfil,))
            self.db.executemany("""INSERT INTO items(drive_id,titulo,autor,tipo,categoria_macro,subcategoria,ruta_relativa,ruta_portada,tamano_bytes,mime_type,perfil_drive,tipo_contenido,formato)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(drive_id) DO UPDATE SET
              titulo=CASE WHEN items.titulo_personalizado=1 THEN items.titulo ELSE excluded.titulo END,
              autor=CASE WHEN items.autor != '' THEN items.autor ELSE excluded.autor END,
              tipo=excluded.tipo,tipo_contenido=excluded.tipo_contenido,formato=excluded.formato,categoria_macro=excluded.categoria_macro,subcategoria=excluded.subcategoria,
              ruta_relativa=excluded.ruta_relativa,ruta_portada=excluded.ruta_portada,tamano_bytes=excluded.tamano_bytes,
              mime_type=excluded.mime_type,perfil_drive=excluded.perfil_drive,
              disponible=1""",rows)
            check_cancelled()
            if not skipped: self.db.execute('DELETE FROM container_entries WHERE perfil_drive=?',(perfil,))
            self.db.executemany('''INSERT INTO container_entries(container_drive_id,drive_id,titulo,ruta_relativa,tamano_bytes,mime_type,perfil_drive)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(drive_id) DO UPDATE SET
                container_drive_id=excluded.container_drive_id,titulo=excluded.titulo,
                ruta_relativa=excluded.ruta_relativa,tamano_bytes=excluded.tamano_bytes,
                mime_type=excluded.mime_type,perfil_drive=excluded.perfil_drive''',entries)
            check_cancelled()
            configurar(self.db,'id_perfil_drive',perfil)
        return dict(indexados=len(rows),omitidos_proto=skipped,perfil=perfil)
    def exportar_libros(self,destino):
        rows=[dict(r) for r in self.db.execute("SELECT drive_id,titulo,ruta_relativa FROM items WHERE tipo='pdf' AND disponible=1 AND perfil_drive=?",(preferencia(self.db,'id_perfil_drive',''),))]
        Path(destino).write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
        return len(rows)
