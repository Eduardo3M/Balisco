"""Local previews and the Drive/Colab cover exchange."""
from pathlib import Path
from io import BytesIO
import json
import os
import subprocess
import sys
import webbrowser
import zipfile

from .drive_sync import ID_PATTERN
from .container_ops import drive_id_for_path
from .items_manager import ItemsManager
from .library_layout import library_root, relative_path, root_id
from .thumbnailer import create_thumbnail


def _source_for(item, manager):
    path=manager.ruta_local(item)
    if item['tipo']!='curso':return path
    if not path.is_dir():raise FileNotFoundError(str(path))
    children=[child for child in path.iterdir() if child.is_file()]
    for suffixes in ({'.jpg','.jpeg','.png','.webp'}, {'.pdf','.epub'}):
        match=next((child for child in sorted(children,key=lambda p:p.name.casefold()) if child.suffix.casefold() in suffixes),None)
        if match:return match
    raise FileNotFoundError('El contenedor no tiene una imagen, PDF o EPUB en su raíz')


def _dehydrate(path):
    if os.name!='nt':return
    try:
        import ctypes
        attributes=ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if attributes==0xFFFFFFFF or attributes & 0x80000:return
        subprocess.run(['attrib','+U','-P',str(path)],capture_output=True,timeout=15,check=False)
    except (OSError,subprocess.TimeoutExpired):pass


def render_local(db, profile, ids, data_dir):
    if not isinstance(ids,list) or not ids or len(ids)>10000 or len(set(ids))!=len(ids):
        raise ValueError('Selección de portadas inválida')
    manager=ItemsManager(db)
    covers=Path(data_dir)/'portadas';covers.mkdir(parents=True,exist_ok=True)
    done=[];failed=[]
    for ident in ids:
        if not isinstance(ident,str) or not ID_PATTERN.fullmatch(ident):raise ValueError('ID inválido')
        item=manager.obtener(ident)
        if item['perfil_drive']!=profile or not item['disponible']:raise ValueError('Selección fuera del perfil activo')
        try:
            source=_source_for(item,manager)
            create_thumbnail(source,covers/(ident+'.jpg'))
            _dehydrate(source)
            done.append(ident)
        except (OSError,ValueError,RuntimeError) as exc:failed.append({'id':ident,'error':str(exc)})
    return {'rendered':len(done),'ids':done,'failed':failed}


def queue_colab(db, profile, ids, data_dir):
    if not root_id(db,profile):raise ValueError('Selecciona una biblioteca vinculada')
    if not isinstance(ids,list) or not ids or len(ids)>10000 or len(set(ids))!=len(ids):
        raise ValueError('Selección de portadas inválida')
    root=library_root(db,profile)
    entries=[]
    for ident in ids:
        if not isinstance(ident,str) or not ID_PATTERN.fullmatch(ident):raise ValueError('ID inválido')
        item=db.execute('SELECT drive_id,ruta_relativa,tipo FROM items WHERE drive_id=? AND perfil_drive=? AND disponible=1',
                        (ident,profile)).fetchone()
        if not item:raise ValueError('Selección fuera del perfil activo')
        path=ItemsManager(db).ruta_local(dict(item,perfil_drive=profile))
        if not path.is_relative_to(root):raise ValueError('Elemento fuera de la biblioteca')
        entries.append({'drive_id':ident,'path':list(path.relative_to(root).parts),'folder':item['tipo']=='curso'})
    hidden=root/'.balisco';hidden.mkdir(exist_ok=True)
    source=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent.parent))/'tools'/'generar_portadas.ipynb'
    if not source.is_file():raise FileNotFoundError('No se encontró el cuaderno de Colab')
    notebook=json.loads(source.read_text(encoding='utf-8'))
    # The first part is Mi unidad / My Drive; Colab always mounts it as MyDrive.
    drive=Path(root.anchor)
    parts=list(root.relative_to(drive).parts)
    if not parts or parts[0] not in ('Mi unidad','My Drive'):raise ValueError('La biblioteca debe estar dentro de Mi unidad')
    notebook['cells'][0]['source']=[line.replace('__BALISCO_ROOT__',json.dumps(parts[1:],ensure_ascii=False)) for line in notebook['cells'][0]['source']]
    notebook_file=hidden/'generar_portadas.ipynb'
    notebook_file.write_text(json.dumps(notebook,ensure_ascii=False,indent=1),encoding='utf-8')
    queue=hidden/'cola_render.json'
    temporary=hidden/'cola_render.tmp'
    temporary.write_text(json.dumps({'version':1,'root_id':root_id(db,profile),'items':entries},ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(temporary,queue)
    relative=relative_path(db,profile,notebook_file,root)
    notebook_id=drive_id_for_path(profile,relative,is_folder=False,timeout=90,allow_hidden=True)
    webbrowser.open('https://colab.research.google.com/drive/'+notebook_id)
    return {'queued':len(entries),'notebook_id':notebook_id}


def collect_batch(db, profile, data_dir):
    if not root_id(db,profile):return {'imported':0}
    hidden=library_root(db,profile)/'.balisco'
    archive=hidden/'portadas_lote.zip'
    if not archive.is_file():return {'imported':0}
    if archive.is_symlink():raise ValueError('Lote de portadas inválido')
    covers=Path(data_dir)/'portadas';covers.mkdir(parents=True,exist_ok=True)
    from PIL import Image
    imported=0;total=0
    with zipfile.ZipFile(archive) as batch:
        files=batch.infolist()
        for entry in files:
            total+=entry.file_size
            if total>200_000_000 or entry.file_size>8_000_000:raise ValueError('Lote de portadas demasiado grande')
            name=Path(entry.filename).name
            if entry.is_dir() or entry.filename!=name or not name.endswith('.jpg') or not ID_PATTERN.fullmatch(name[:-4]):
                raise ValueError('El lote contiene una ruta o un ID inválido')
            if not db.execute('SELECT 1 FROM items WHERE drive_id=? AND perfil_drive=?',(name[:-4],profile)).fetchone():
                raise ValueError('El lote contiene un ID ajeno al perfil activo')
        for entry in files:
            target=covers/entry.filename
            if target.exists():continue
            raw=batch.read(entry)
            with Image.open(BytesIO(raw)) as image:
                if image.format!='JPEG' or image.width*image.height>30_000_000:
                    raise ValueError('Imagen de portada inválida')
                image.verify()
            temporary=target.with_suffix('.tmp')
            try:
                temporary.write_bytes(raw)
                os.replace(temporary,target)
            finally:temporary.unlink(missing_ok=True)
            imported+=1
    archive.unlink()
    return {'imported':imported}
