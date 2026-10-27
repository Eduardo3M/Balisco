"""Thread-safe, narrow desktop bridge. All content access is explicit."""
import base64
from contextlib import closing
from io import BytesIO
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import sqlite3
import stat
import threading
import time
import uuid
import webbrowser
from .database import DATA_DIR, conectar, configurar, preferencia, normalize_tag, normalize_search
from .items_manager import ItemsManager
from .tags_manager import TagsManager, obtener_etiquetas_ordenadas_frecuencia, obtener_sugerencias_etiquetas
from .search_parser import agregar_filtro, limpiar_todos_filtros, construir_query_sql, internal_searchable, internal_filterable, is_tracked_container_item
from .serendipity import obtener_aleatorio_puro, obtener_semi_aleatorio_contextual, obtener_similares
from .drive_sync import (DriveSync, Metadata, conectar_db_drive_ro, detectar_perfiles_drive,
                         extraer_ids_proto, ID_PATTERN, obtener_letra_drive, cambiar_perfil_activo, classify_file)
from .backup_manager import crear_backup_en_biblioteca
from .metadata_editor import edit_taxonomy
from .container_ops import (assign_items, ungroup_container, import_container_folder,
                            import_library_file, library_root, inside, extract_to_library, ImportCancelled)
from .cleaner import clean_book_title_and_author
from .library_layout import root_id, relative_path, INBOX, cleanup_category

class DesktopAPI:
    def __init__(self, data_dir=None, started=None):
        self._storage=None
        if data_dir is None:
            from .profile_storage import ProfileStorage
            self._storage=ProfileStorage(DATA_DIR)
        self._dir=self._storage.directory() if self._storage else Path(data_dir)
        self._dbpath=self._dir/'biblioteca.db'
        self._lock=threading.RLock()
        self._sync_lock=threading.RLock()
        self._containers={}
        self._container_cache_info={}
        self._profile_sources=None
        self._imports={}
        self._imports_lock=threading.RLock()
        self._undo_deletions=[]
        self._started=started or time.perf_counter()
        self._cover_ids_cache=None
        self._auto_thumbs_cache=None
        if not self._storage:
            from .migrations import migrate_author,migrate_interested,migrate_legacy_course_items,migrate_item_file_types
            for migration in (migrate_author,migrate_interested,migrate_legacy_course_items,migrate_item_file_types):migration(self._dbpath)
        with closing(conectar(self._dbpath)) as db:
            if 'autor' not in {r[1] for r in db.execute('PRAGMA table_info(items)')}:
                raise RuntimeError('La base requiere la migración de autor de Fase 1 antes de iniciar.')
    def _ensure_cover_cache(self):
        if self._cover_ids_cache is None:
            covers_dir=self._dir/'portadas'
            self._cover_ids_cache={f.stem for f in covers_dir.glob('*.jpg') if not f.is_symlink() and f.stat().st_size<=8_000_000} if covers_dir.is_dir() else set()
            auto_dir=self._dir/'portadas_auto'
            self._auto_thumbs_cache={f.name for f in auto_dir.glob('*.jpg') if not f.is_symlink() and f.stat().st_size<=8_000_000} if auto_dir.is_dir() else set()

    def _invalidate_cover_cache(self):
        self._cover_ids_cache=None
        self._auto_thumbs_cache=None

    def _item_has_cover(self, item, profile=None):
        if item.get('folder'): return False
        self._ensure_cover_cache()
        ident=item.get('drive_id') or item.get('id')
        if ident and ident in self._cover_ids_cache: return True
        prof=profile or item.get('perfil_drive') or ''
        rel=item.get('ruta_relativa') or item.get('path') or ''
        if prof and rel:
            from .thumbnailer import thumbnail_name
            t_name=thumbnail_name(prof, rel)
            if t_name in self._auto_thumbs_cache: return True
        return False

    def _connect(self):
        db=sqlite3.connect(self._dbpath,timeout=10)
        db.create_function('unicode_casefold',1,lambda value: str(value or '').casefold(),deterministic=True)
        db.create_function('normalize_tag',1,normalize_tag,deterministic=True)
        db.create_function('normalize_search',1,normalize_search,deterministic=True)
        db.row_factory=sqlite3.Row
        return db
    def _open_active_profile(self,profile):
        self._storage.activate(profile)
        self._dir=self._storage.directory()
        self._dbpath=self._storage.database()
        chrome=getattr(self,'_chrome',None)
        if chrome:chrome.db_path=self._dbpath
        self._containers.clear();self._container_cache_info.clear();self._profile_sources=None
        self._undo_deletions.clear();self._invalidate_cover_cache()
        with self._imports_lock:self._imports.clear()
    def _select_only_available_profile(self):
        if not self._storage or self._storage.active:return
        valid=[p['id'] for p in detectar_perfiles_drive() if not p.get('error')]
        if len(valid)==1:
            with self._lock,self._sync_lock:self._open_active_profile(valid[0])
    WINDOW_ACTIONS = frozenset({'close', 'window_minimize', 'window_toggle_maximize', 'window_set_fullscreen',
                                'window_drag', 'window_resize', 'window_state', 'window_snap'})
    def call(self, action, payload=None):
        """Only this method is exposed to JS. Never accept executable SQL or paths."""
        try:
            if action in ('bootstrap','drive_status','sync'):self._select_only_available_profile()
            if action=='import_status':
                with self._imports_lock:
                    job=self._imports.get(str((payload or {}).get('id')))
                    public={key:value for key,value in (job or {'state':'unknown','message':'Importación no encontrada'}).items() if key in {'id','state','phase','kind','name','message','data','error'}}
                    return {'ok':True,'data':public}
            if action=='import_jobs':
                with self._imports_lock:return {'ok':True,'data':[{key:value for key,value in job.items() if key in {'id','state','phase','kind','name','message','error'}} for job in self._imports.values()]}
            if action=='start_import': return {'ok':True,'data':self._start_import((payload or {}).get('path'),(payload or {}).get('active_tag'))}
            if action=='cancel_import': return {'ok':True,'data':self._cancel_import(str((payload or {}).get('id','')))}
            if action=='delete_import': return {'ok':True,'data':self._delete_import(str((payload or {}).get('id','')))}
            if action=='sync':
                with self._sync_lock, closing(self._connect()) as db:return {'ok':True,'data':self._dispatch(db,action,payload or {})}
            if action in self.WINDOW_ACTIONS:
                return {'ok':True,'data':self._window_action(action,payload or {})}
            with self._lock, closing(self._connect()) as db:
                value=self._dispatch(db,action,payload or {})
            return {'ok':True,'data':value}
        except Exception as exc:
            return {'ok':False,'error':str(exc),'kind':type(exc).__name__}
    def _start_import(self,path,active_tag=None):
        from pathlib import Path
        if not isinstance(path,str) or not path.strip():raise ValueError('Selecciona un archivo o carpeta válido')
        candidate=Path(str(path or ''))
        if candidate.is_symlink():raise ValueError('No se pueden importar enlaces simbólicos')
        source=candidate.resolve()
        if not source.exists() or (not source.is_file() and not source.is_dir()):raise ValueError('Selecciona un archivo o carpeta válido')
        if active_tag:
            from .library_layout import category_name
            active_tag=category_name(active_tag)
        ident=uuid.uuid4().hex
        kind='folder' if source.is_dir() else 'file'
        with self._imports_lock:
            finished=[key for key,job in self._imports.items() if job.get('state') in ('done','error')]
            for key in finished[:-49]:self._imports.pop(key,None)
            self._imports[ident]={'id':ident,'state':'running','phase':'preparando','kind':kind,'name':source.name,'message':'Preparando importación','active_tag':active_tag}
        threading.Thread(target=self._run_import,args=(ident,source,kind),daemon=True).start()
        return {'id':ident,'kind':kind,'name':source.name}
    def _cancel_import(self,ident):
        with self._imports_lock:
            job=self._imports.get(ident)
            if not job or job.get('state')!='running':return {'cancelled':False,'message':'La operación ya terminó.'}
            job['cancel_requested']=True
            job['message']='Cancelando y eliminando lo copiado…'
            return {'cancelled':True,'message':job['message']}
    def _delete_import(self,ident):
        with self._imports_lock:
            job=self._imports.get(ident)
            if not job or job.get('state')!='done':raise ValueError('Solo puedes eliminar cargas completadas')
            job['state']='deleting';job['message']='Eliminando copia de Drive…'
        try:
            message=self._remove_cancelled_import(ident)
            with self._imports_lock:self._imports[ident].update(state='deleted',phase='deleted',message='Copia eliminada de Drive')
            return {'deleted':True,'message':message or 'No se encontró la copia.'}
        except Exception as exc:
            with self._imports_lock:self._imports[ident].update(state='done',message=str(exc))
            raise
    def _is_import_cancelled(self,ident):
        with self._imports_lock:return bool(self._imports.get(ident,{}).get('cancel_requested'))
    def _set_import_target(self,ident,path,kind,profile):
        with self._imports_lock:
            if ident in self._imports:self._imports[ident].update(target_path=path,target_kind=kind,profile=profile)
    def _set_import_drive_id(self,ident,drive_id):
        with self._imports_lock:
            if ident in self._imports:self._imports[ident]['drive_id']=drive_id
    def _remove_cancelled_import(self,ident):
        with self._imports_lock:job=dict(self._imports.get(ident,{}))
        raw_path=job.get('target_path')
        if not raw_path:return None
        with self._lock,closing(self._connect()) as db:
            profile=job.get('profile') or preferencia(db,'id_perfil_drive','')
            library=library_root(db,profile)
            target=Path(raw_path)
            kind=job.get('target_kind')
            category=job.get('active_tag') or INBOX if root_id(db,profile) else ('Containers' if kind=='folder' else 'Storage')
            expected_parent=(library/category).resolve()
            if target.parent.resolve()!=expected_parent:raise ValueError('No se pudo verificar la ruta de la copia cancelada')
            relative=relative_path(db,profile,target,library) if root_id(db,profile) else str(PureWindowsPath(library.parent.name,'Biblioteca',category,target.name))
        def remove_readonly(function,path,_error):
            os.chmod(path,stat.S_IWRITE|stat.S_IREAD)
            function(path)
        removal_error=None
        for attempt in range(5):
            try:
                if target.is_symlink():target.unlink()
                elif target.is_dir():shutil.rmtree(target,onerror=remove_readonly)
                elif target.exists():
                    try:os.chmod(target,stat.S_IWRITE|stat.S_IREAD)
                    except OSError:pass
                    target.unlink()
                removal_error=None;break
            except OSError as exc:
                removal_error=exc;time.sleep(.2*(attempt+1))
        if removal_error and target.exists():raise removal_error
        with self._lock,self._sync_lock,closing(self._connect()) as db:
            with db:
                if kind=='folder':
                    row=db.execute('SELECT drive_id FROM items WHERE ruta_relativa=? AND perfil_drive=?',(relative,profile)).fetchone()
                    drive_id=job.get('drive_id') or (row['drive_id'] if row else None)
                    if drive_id:
                        db.execute('''INSERT INTO pending_container_moves(drive_id,expected_relative,container_drive_id,perfil_drive)
                            VALUES(?,'','__removed__',?) ON CONFLICT(drive_id) DO UPDATE SET
                            expected_relative='',container_drive_id='__removed__',created_at=CURRENT_TIMESTAMP''',(drive_id,profile))
                        db.execute('DELETE FROM container_entries WHERE container_drive_id=?',(drive_id,))
                        db.execute('DELETE FROM items WHERE drive_id=?',(drive_id,))
                else:
                    row=db.execute('''SELECT drive_id,tipo FROM items WHERE ruta_relativa=? AND perfil_drive=?
                        AND disponible=1 ORDER BY id DESC LIMIT 1''',(relative,profile)).fetchone()
                    drive_id=job.get('drive_id') or (row['drive_id'] if row else None)
                    if drive_id:
                        db.execute('''INSERT INTO pending_container_moves(drive_id,expected_relative,container_drive_id,perfil_drive)
                            VALUES(?,?,'__removed__',?) ON CONFLICT(drive_id) DO UPDATE SET
                            expected_relative=excluded.expected_relative,container_drive_id='__removed__',
                            created_at=CURRENT_TIMESTAMP''',(drive_id,relative,profile))
                        if row and row['tipo']=='pdf':
                            db.execute('UPDATE items SET disponible=0 WHERE drive_id=?',(drive_id,))
                        else:
                            db.execute('DELETE FROM items WHERE drive_id=?',(drive_id,))
        with self._lock:self._containers.clear();self._container_cache_info.clear()
        return 'La copia de esta operación se eliminó de la unidad local de Drive; DriveFS propagará el borrado a Google Drive.'
    def _set_import_phase(self,ident,phase,detail=None):
        messages={'copiando':'Copiando a la unidad de Drive · aprox. 10–70%…','copia_completa':'Copia local completa · aprox. 75%; esperando a DriveFS…','esperando_drive':'Copia terminada · aprox. 80%; esperando registro de DriveFS…','registrando':'DriveFS reconoció el elemento · aprox. 85%; registrándolo…','sincronizando':'Sincronizando la biblioteca · aprox. 90%…','verificando':'Verificando que aparezca en Balisco · aprox. 95%…'}
        if phase=='copiando':
            import re
            match=re.search(r'(\d+)%',str(detail or ''))
            detail=f'Subiendo a Drive · {match.group(1)}%' if match else 'Subiendo a Drive'
        with self._imports_lock:
            if ident in self._imports and not self._imports[ident].get('cancel_requested'):
                self._imports[ident].update(phase=phase,message=detail or messages.get(phase,phase))
    def _run_import(self,ident,source,kind):
        try:
            with closing(self._connect()) as db:
                profile=preferencia(db,'id_perfil_drive','')
                cancelled=lambda:self._is_import_cancelled(ident)
                def check_cancelled():
                    if cancelled():raise ImportCancelled()
                progress=lambda phase,detail=None:self._set_import_phase(ident,phase,detail)
                on_target=lambda path,target_kind:self._set_import_target(ident,path,target_kind,profile)
                with self._imports_lock:active_tag=self._imports.get(ident,{}).get('active_tag')
                if cancelled():raise ImportCancelled()
                if kind=='folder':
                    data=import_container_folder(db,profile,str(source),progress=progress,cancelled=cancelled,on_target=on_target,active_tag=active_tag)
                else:
                    data=import_library_file(db,profile,str(source),progress=progress,cancelled=cancelled,on_target=on_target,
                                             thumbnail_dir=None if root_id(db,profile) else self._dir/'portadas_auto',active_tag=active_tag)
                if root_id(db,profile):
                    from .container_ops import drive_id_for_path
                    from .cover_engine import _dehydrate
                    from .thumbnailer import create_thumbnail
                    with self._imports_lock:target_path=self._imports.get(ident,{}).get('target_path')
                    if target_path:
                        relative=relative_path(db,profile,target_path,library_root(db,profile))
                        imported_id=drive_id_for_path(profile,relative,is_folder=kind=='folder',timeout=90,cancelled=cancelled)
                        self._set_import_drive_id(ident,imported_id)
                        data['id']=imported_id
                        try:
                            target=Path(target_path)
                            if kind=='folder':
                                options=[child for child in target.iterdir() if child.is_file()]
                                options=sorted(options,key=lambda child:(child.suffix.casefold() not in ('.jpg','.jpeg','.png','.webp'),child.suffix.casefold() not in ('.pdf','.epub'),child.name.casefold()))
                                candidate=next((child for child in options if child.suffix.casefold() in ('.jpg','.jpeg','.png','.webp','.pdf','.epub')),None)
                            else:candidate=target
                            if candidate:
                                create_thumbnail(candidate,self._dir/'portadas'/(imported_id+'.jpg'))
                                _dehydrate(candidate)
                                self._invalidate_cover_cache()
                        except Exception:
                            import logging
                            logging.getLogger(__name__).exception('No se pudo generar la portada del elemento importado')
            with self._lock:self._containers.clear();self._container_cache_info.clear()
            with self._imports_lock:
                cancelled_at_finish=self._imports[ident].get('cancel_requested')
                if not cancelled_at_finish:
                    self._imports[ident].update(state='done',phase='done',message='Copia local completada',data=data)
            if cancelled_at_finish:raise ImportCancelled()
        except ImportCancelled as exc:
            try:message=self._remove_cancelled_import(ident) or 'No había una copia que eliminar.'
            except Exception as cleanup_error:message=f'No se completó la limpieza de Drive: {cleanup_error}'
            with self._imports_lock:self._imports[ident].update(state='cancelled',phase='cancelled',message=message,error=message)
        except Exception as exc:
            with self._imports_lock:self._imports[ident].update(state='error',phase='error',message=str(exc),error=str(exc))
    def _window_action(self, action, p):
        """Controles de la ventana sin marco. No tocan la base de datos ni el lock."""
        chrome=getattr(self,'_chrome',None)
        if action=='close':
            self._allow_close=True
            finish=getattr(self,'_finish_close',None)
            if finish: threading.Thread(target=finish,daemon=True).start()
            elif getattr(self,'_window',None): threading.Thread(target=self._window.destroy,daemon=True).start()
            return True
        if chrome is None: return None
        if action=='window_minimize': return chrome.minimize()
        if action=='window_toggle_maximize': return {'maximized':chrome.toggle_maximize()}
        if action=='window_set_fullscreen': return {'fullscreen':chrome.set_fullscreen(bool(p.get('enabled')))}
        if action=='window_state': return {'maximized':chrome.is_maximized()}
        if action=='window_drag': return chrome.drag(float(p.get('rx',0.5)),int(p.get('oy',20)))
        if action=='window_snap': return chrome.snap()
        if action=='window_resize': return chrome.resize(str(p.get('edge','')))
        return None
    def _ensure_cover_on_open(self,profile,ident,file_path,rel=''):
        try:
            if not ident or not ID_PATTERN.fullmatch(str(ident)) or not file_path or not Path(file_path).is_file():return False
            dest=self._dir/'portadas'/(f'{ident}.jpg')
            if dest.is_file() and not dest.is_symlink():return False
            if rel:
                from .thumbnailer import thumbnail_name
                auto_dest=self._dir/'portadas_auto'/thumbnail_name(profile,rel)
                if auto_dest.is_file() and not auto_dest.is_symlink():return False
            from .thumbnailer import create_thumbnail
            dest.parent.mkdir(parents=True,exist_ok=True)
            create_thumbnail(Path(file_path),dest)
            self._invalidate_cover_cache()
            return dest.is_file()
        except Exception:
            return False
    def _item(self,db,ident):
        item=ItemsManager(db).obtener(ident)
        if item['perfil_drive']!=preferencia(db,'id_perfil_drive','') or not item['disponible']:
            raise ValueError('Elemento fuera del perfil activo')
        return item
    def _capture_deletion(self,db,path,ids,container_id=None):
        ids=set(ids)
        marks=','.join('?' for _ in ids)
        items=[dict(row) for row in db.execute(f'SELECT * FROM items WHERE drive_id IN ({marks})',tuple(ids))] if ids else []
        entries=[dict(row) for row in db.execute(f'SELECT * FROM container_entries WHERE drive_id IN ({marks})'+
                 (' OR container_drive_id=?' if container_id else ''),(*ids,*([container_id] if container_id else [])))] if ids or container_id else []
        moves=[dict(row) for row in db.execute(f'SELECT * FROM pending_container_moves WHERE drive_id IN ({marks})',tuple(ids))] if ids else []
        return {'path':str(path),'ids':ids,'items':items,'entries':entries,'moves':moves}
    def _remember_deletion(self,snapshot):
        self._undo_deletions.append(snapshot)
    def _undo_deletion(self,db):
        if not self._undo_deletions: return {'restored':False}
        from .recycle_undo import restore_from_recycle_bin
        snapshot=self._undo_deletions[-1]
        restore_from_recycle_bin(snapshot['path'])
        with db:
            for row in snapshot['items']:
                columns=list(row)
                db.execute(f"INSERT OR REPLACE INTO items ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",tuple(row.values()))
            for row in snapshot['entries']:
                columns=list(row)
                db.execute(f"INSERT OR REPLACE INTO container_entries ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",tuple(row.values()))
            for ident in snapshot['ids']:
                db.execute('DELETE FROM pending_container_moves WHERE drive_id=?',(ident,))
            for row in snapshot['moves']:
                columns=list(row)
                db.execute(f"INSERT INTO pending_container_moves ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",tuple(row.values()))
        self._undo_deletions.pop()
        self._containers.clear(); self._container_cache_info.clear()
        return {'restored':True,'name':Path(snapshot['path']).name}
    def _internal_searchable(self,db,item,cache):
        return internal_searchable(db,item,cache)
    def _container_payload(self,db,container_id,profile):
        records=list(self._containers[container_id].values())
        metadata={row['drive_id']:dict(row) for row in db.execute('''SELECT drive_id,titulo,autor,etiquetas,rating,
            es_favorito,estado_lectura,tipo_contenido,formato,fijado,oculto,idioma,search_override,mostrar_en_filtros,ultimo_acceso,recent_hidden
            FROM items WHERE container_parent=? AND perfil_drive=? AND disponible=1''',(container_id,profile))}
        for record in records:
            if record['id'] in metadata:record.update(metadata[record['id']])
            record['has_cover']=bool(self._item_has_cover(record, profile))
        return [{key:value for key,value in record.items() if key!='path'} for record in records]
    def _dispatch(self,db,action,p):
        profile=preferencia(db,'id_perfil_drive','')
        manager=ItemsManager(db)
        if action=='drive_status':
            from .drive_setup import status
            return status(db)
        if action=='drive_install':
            from .drive_setup import open_install_page
            return open_install_page()
        if action=='drive_start':
            from .drive_setup import launch_drive
            return launch_drive()
        if action=='library_pick':
            from .drive_setup import link_folder
            from tkinter import Tk, filedialog
            root=Tk();root.withdraw();root.attributes('-topmost',True)
            try:path=filedialog.askdirectory(parent=root,title='Selecciona tu biblioteca en Google Drive')
            finally:root.destroy()
            return link_folder(db,profile,path) if path else None
        if action=='library_create':
            from .drive_setup import link_folder
            from .container_ops import valid_name
            from tkinter import Tk, filedialog
            root=Tk();root.withdraw();root.attributes('-topmost',True)
            try:parent=filedialog.askdirectory(parent=root,title='Selecciona dónde crear la biblioteca')
            finally:root.destroy()
            if not parent:return None
            name=valid_name(p.get('name','Biblioteca'))
            parent=Path(parent).resolve()
            drive=Path(preferencia(db,'unidad_drive:'+profile)).resolve() if preferencia(db,'unidad_drive:'+profile) else Path(parent.anchor)
            if not parent.is_relative_to(drive):raise ValueError('Selecciona una ubicación dentro de Google Drive')
            parts=parent.relative_to(drive).parts
            if not parts or parts[0] not in ('Mi unidad','My Drive'):
                raise ValueError('Selecciona una ubicación dentro de Mi unidad')
            folder=parent/name
            folder.mkdir()
            return link_folder(db,profile,folder)
        if action=='migration_preview':
            from .migrations import library_migration_preview
            return library_migration_preview(db,profile)
        if action=='migration_run':
            from .migrations import migrate_library_layout
            return migrate_library_layout(db,profile)
        if action=='render_covers_local':
            from .cover_engine import render_local
            result=render_local(db,profile,p.get('ids'),self._dir)
            self._invalidate_cover_cache()
            return result
        if action=='render_covers_colab':
            from .cover_engine import queue_colab
            return queue_colab(db,profile,p.get('ids'),self._dir)
        if action=='cover_batch_check':
            from .cover_engine import collect_batch
            result=collect_batch(db,profile,self._dir)
            if result['imported']:self._invalidate_cover_cache()
            return result
        if action=='bootstrap':
            row_langs=db.execute("SELECT valor FROM configuracion WHERE clave='idiomas'").fetchone()
            languages=json.loads(row_langs['valor']) if row_langs and row_langs['valor'] else ['Español', 'Inglés']
            return {'prefs':{r['clave']:r['valor'] for r in db.execute("SELECT * FROM configuracion WHERE clave IN ('tema','zoom','modo','id_perfil_drive','wallpaper','wallpaper_opacity','wallpaper_blur','wallpaper_positions','container_wallpaper','container_background_opacity','container_background_blur','confirm_delete','show_recent_titles')")},'languages':languages,'count':db.execute("SELECT count(*) FROM items WHERE disponible=1 AND oculto=0 AND container_parent='' AND perfil_drive=?",(profile,)).fetchone()[0]}
        if action=='undo_delete': return self._undo_deletion(db)
        if action=='ready':
            metrics={'ready_ms':round((time.perf_counter()-self._started)*1000,1),'renderer':'edgechromium','frontend':p}
            (self._dir/'performance.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
            return metrics
        if action=='query':
            filters=limpiar_todos_filtros()
            for token in p.get('tokens',[]): filters=agregar_filtro(str(token),filters)
            sql,args=construir_query_sql(filters,profile)
            sql=sql.replace('SELECT i.*','SELECT i.drive_id,i.titulo,i.autor,i.idioma,i.tipo,i.tipo_contenido,i.formato,i.estado_lectura,i.es_favorito,i.rating,i.tamano_bytes,i.categoria_macro,i.indexar_contenido,i.oculto,i.container_parent,i.fijado,i.search_override,i.mostrar_en_filtros,i.ruta_relativa,i.perfil_drive')
            items=[dict(r) for r in db.execute(sql,args)]
            has_text=any(p['tipo']=='texto_titulo' for p in filters['pildoras']);has_filter=any(p['tipo'] not in ('orden','ocultos','historial') for p in filters['pildoras'])
            if has_text or has_filter:
                cache={};filter_cache={}
                items=[item for item in items if ((self._internal_searchable(db,item,cache) or (is_tracked_container_item(item) and internal_filterable(db,item,filter_cache))) if has_text else internal_filterable(db,item,filter_cache))]
            if any(p['tipo']=='sin_portada' for p in filters['pildoras']):
                items=[item for item in items if not self._item_has_cover(item, profile)]
            elif any(p['tipo']=='con_portada' for p in filters['pildoras']):
                items=[item for item in items if self._item_has_cover(item, profile)]
            for item in items:
                item['has_cover']=bool(self._item_has_cover(item, profile))
            total=db.execute("SELECT count(*) FROM items WHERE perfil_drive=? AND disponible=1 AND oculto=0 AND container_parent=''",(profile,)).fetchone()[0]
            return {'items':items,'total':total,'filters':filters['pildoras']}
        if action=='set_deep_search':
            item=self._item(db,p['id'])
            if item['tipo']!='curso' or item['container_parent'] or type(p.get('enabled')) is not bool:
                raise ValueError('Configuración del contenedor inválida')
            enabled=int(p['enabled'])
            if enabled and not db.execute('SELECT 1 FROM items WHERE container_parent=? AND perfil_drive=? LIMIT 1',
                                          (item['drive_id'],profile)).fetchone():
                try:self._dispatch(db,'container',{'id':item['drive_id']})
                except FileNotFoundError:pass
            with db:db.execute('UPDATE items SET indexar_contenido=? WHERE id=?',(enabled,item['id']))
            return {'indexar_contenido':int(p['enabled'])}
        if action=='detail':
            item=self._item(db,p['id']); item['url']=manager.url(p['id'])
            if item.get('container_parent'):
                parent=db.execute('SELECT titulo FROM items WHERE drive_id=?',(item['container_parent'],)).fetchone()
                item['container_title']=parent['titulo'] if parent else ''
            return item
        if action=='update':
            self._item(db,p['id'])
            methods={'titulo':manager.cambiar_titulo,'autor':manager.cambiar_autor,'idioma':manager.cambiar_idioma,'notas':manager.actualizar_notas,'rating':manager.cambiar_rating,'estado_lectura':manager.cambiar_estado_lectura,'es_favorito':manager.cambiar_favorito,'etiquetas':TagsManager(db).actualizar_etiquetas_item}
            if p['field'] not in methods: raise ValueError('Campo no editable')
            methods[p['field']](p['id'],p['value']); return self._item(db,p['id'])
        if action=='bulk_rename':
            updates=p.get('updates')
            if not isinstance(updates,list) or not 1<=len(updates)<=10000:
                raise ValueError('Selección inválida')
            titles={}
            for entry in updates:
                if not isinstance(entry,dict) or not isinstance(entry.get('id'),str) or not isinstance(entry.get('title'),str):
                    raise ValueError('Título inválido')
                ident=entry['id']; title=entry['title'].strip()
                if ident in titles or not title or len(title)>500 or '\n' in title or '\r' in title:
                    raise ValueError('Título inválido')
                titles[ident]=title
            items=[self._item(db,ident) for ident in titles]
            with db:
                db.executemany('UPDATE items SET titulo=?,titulo_personalizado=1 WHERE id=?',
                               [(titles[item['drive_id']],item['id']) for item in items])
            for records in self._containers.values():
                for ident,title in titles.items():
                    if ident in records: records[ident]['title']=title
            return {'updated':len(items)}
        if action=='selection_properties':
            ids=p.get('ids')
            if not isinstance(ids,list) or not ids or len(ids)>10000 or len(ids)!=len(set(ids)) or any(not isinstance(ident,str) for ident in ids):
                raise ValueError('Selección inválida')
            fields=('fijado','es_favorito','oculto','mostrar_en_filtros','rating','estado_lectura','idioma')
            columns=','.join(f'MIN({field}) AS min_{field},MAX({field}) AS max_{field}' for field in fields)
            result={}
            for start in range(0,len(ids),500):
                chunk=ids[start:start+500]
                marks=','.join('?' for _ in chunk)
                row=db.execute(f'SELECT COUNT(*) AS total,SUM(CASE WHEN ultimo_acceso IS NOT NULL AND recent_hidden=0 THEN 1 ELSE 0 END) AS recent_count,{columns} FROM items WHERE perfil_drive=? AND disponible=1 AND drive_id IN ({marks})',
                               [profile,*chunk]).fetchone()
                if row['total']!=len(chunk):raise ValueError('Selección fuera del perfil activo')
                result['recent_count']=result.get('recent_count',0)+row['recent_count']
                for field in fields:
                    value=row[f'min_{field}'] if row[f'min_{field}']==row[f'max_{field}'] else None
                    if field not in result:result[field]=value
                    elif result[field]!=value:result[field]=None
            return result
        if action=='selection_tags':
            from collections import Counter
            from .tags_manager import normalizar
            ids=p.get('ids')
            if not isinstance(ids,list) or not ids or len(ids)>10000 or len(ids)!=len(set(ids)) or any(not isinstance(ident,str) for ident in ids):
                raise ValueError('Selección inválida')
            counts=Counter()
            for ident in ids:
                counts.update(normalizar(self._item(db,ident)['etiquetas']))
            return {'total':len(ids),'tags':[{'tag':tag,'count':count} for tag,count in sorted(counts.items(),key=lambda row:(-row[1],row[0]))]}
        if action=='bulk_update':
            ids=p.get('ids');field=p.get('field');value=p.get('value')
            if not isinstance(ids,list) or not ids or len(ids)>10000 or len(ids)!=len(set(ids)):
                raise ValueError('Selección inválida')
            if field in ('es_favorito','fijado','oculto','mostrar_en_filtros') and type(value) is bool:value=int(value)
            elif field=='rating' and type(value) is int and value in range(6):pass
            elif field=='estado_lectura' and value in ('pendiente','interesado','leyendo','leido','abandonado'):pass
            elif field=='idioma' and isinstance(value,str):pass
            else:raise ValueError('Cambio masivo inválido')
            items=[self._item(db,ident) for ident in ids]
            with db:db.executemany('UPDATE items SET '+field+'=? WHERE id=?',[(value,item['id']) for item in items])
            return {'updated':len(items)}
        if action=='set_search_override':
            ids=p.get('ids');value=p.get('value')
            if not isinstance(ids,list) or not ids or len(ids)>10000 or len(ids)!=len(set(ids)) or type(value) is not int or value not in (-1,0,1):
                raise ValueError('Selección de búsqueda inválida')
            items=[self._item(db,ident) for ident in ids]
            items=[item for item in (self._item(db,ident) for ident in ids) if item['container_parent']]
            if not items:raise ValueError('Selecciona contenido de un contenedor')
            with db:db.executemany('UPDATE items SET search_override=? WHERE id=?',[(value,item['id']) for item in items])
            return {'updated':len(items)}
        if action=='remove_recent':
            item=self._item(db,p['id'])
            with db:db.execute('UPDATE items SET recent_hidden=1 WHERE id=?',(item['id'],))
            return True
        if action=='bulk_remove_recent':
            ids=p.get('ids')
            if not isinstance(ids,list) or not ids or len(ids)>10000 or len(ids)!=len(set(ids)) or any(not isinstance(ident,str) for ident in ids):
                raise ValueError('Selección inválida')
            items=[self._item(db,ident) for ident in ids]
            with db:
                changed=db.executemany('UPDATE items SET recent_hidden=1 WHERE id=? AND ultimo_acceso IS NOT NULL AND recent_hidden=0',
                                       [(item['id'],) for item in items]).rowcount
            return {'updated':changed}
        if action=='tags': return obtener_etiquetas_ordenadas_frecuencia(db,profile)
        if action=='tag_suggestions': return obtener_sugerencias_etiquetas(db,profile)
        if action=='taxonomy_edit':
            return edit_taxonomy(db,profile,p.get('kind'),p.get('operation'),p.get('old'),p.get('new',''))
        if action=='authors':
            from collections import Counter
            counts=Counter(name.strip() for row in db.execute('SELECT autor FROM items WHERE disponible=1 AND oculto=0 AND perfil_drive=?',(profile,)) for name in row[0].splitlines() if name.strip())
            return [dict(author=name,total=count) for name,count in sorted(counts.items(),key=lambda x:(-x[1],x[0].casefold()))]
        if action=='bulk_metadata':
            from .tags_manager import normalizar
            ids=p.get('ids',[]); field=p.get('field'); operation=p.get('operation'); value=str(p.get('value','')).strip()
            if not isinstance(ids,list) or not ids or len(ids)>10000 or len(set(ids))!=len(ids): raise ValueError('Selección inválida')
            if field not in ('autor','etiquetas') or operation not in ('add','remove','set') or not value: raise ValueError('Cambio masivo inválido')
            if field=='etiquetas' and len(normalizar(value))!=1: raise ValueError('Una etiqueta por cambio')
            if field=='autor' and ('\n' in value or '\r' in value): raise ValueError('Un autor por cambio')
            items=[self._item(db,ident) for ident in ids]
            tag_changes=[]
            if field=='etiquetas':
                for item in items:
                    names=normalizar(item['etiquetas']); name=normalizar(value)[0]
                    if operation=='add' and name not in names:names.append(name)
                    elif operation=='remove':names=[tag for tag in names if tag!=name]
                    elif operation=='set':names=[name,*[tag for tag in names if tag!=name]]
                    tag_changes.append((item,names))
                if root_id(db,profile):
                    from .library_layout import preflight_moves
                    preflight_moves(db,tag_changes)
            if field=='etiquetas':
                tag_manager=TagsManager(db)
                for item,names in tag_changes:
                    tag_manager.actualizar_etiquetas_item(item['drive_id'],' '.join('+'+tag for tag in names))
            else:
                for item in items:
                    names=[name.strip() for name in item['autor'].splitlines() if name.strip()]
                    if operation=='add' and not any(name.casefold()==value.casefold() for name in names): names.append(value)
                    elif operation=='remove': names=[name for name in names if name.casefold()!=value.casefold()]
                    updated='\n'.join(names)
                    with db:db.execute('UPDATE items SET autor=? WHERE id=?',(updated,item['id']))
            return {'updated':len(items)}
        if action=='random':
            fn=obtener_semi_aleatorio_contextual if p.get('contextual') else obtener_aleatorio_puro
            return fn(db,perfil=profile)
        if action=='similar':
            self._item(db,p['id'])
            return obtener_similares(db,p['id'],profile)
        if action=='open':
            item=self._item(db,p['id']); result=manager.abrir_item(p['id'],p.get('mode','web'))
            if item['tipo']!='curso':
                try:self._ensure_cover_on_open(profile,p['id'],manager.ruta_local(item),item.get('ruta_relativa') or '')
                except Exception:pass
            with db:db.execute('UPDATE items SET recent_hidden=0 WHERE drive_id=?',(p['id'],))
            return result
        if action=='player_open':
            from .player_server import get_player_server
            ident=str(p.get('id',''));container_id=str(p.get('container') or '')
            if not ID_PATTERN.fullmatch(ident):raise ValueError('ID inválido')
            path=None;item_meta=None
            if container_id:
                container=self._item(db,container_id)
                if container_id not in self._containers:
                    self._dispatch(db,'container',{'id':container_id})
                record=self._containers.get(container_id,{}).get(ident)
                if record:
                    if record.get('folder'):raise ValueError('Abre una carpeta desde la vista del contenedor')
                    path=manager.ruta_local(dict(container,ruta_relativa=record['path']))
                    row=db.execute('SELECT * FROM items WHERE drive_id=? AND perfil_drive=?',(ident,profile)).fetchone()
                    item_meta=dict(row) if row else {'drive_id':ident,'titulo':Path(record['title']).stem,'formato':Path(record['path']).suffix.lstrip('.').upper()}
                    item_meta['container_id']=container_id
            if path is None:
                item=self._item(db,ident)
                if item['tipo']=='curso':raise ValueError('Los contenedores se abren en el explorador')
                path=manager.ruta_local(item)
                if not path.exists():path=Path(manager.auto_reparar_ruta(ident))
                item_meta=dict(item,container_id=item.get('container_parent') or '')
            if not path.is_file():raise FileNotFoundError(f'El archivo no está disponible en el equipo: {path.name}')
            with db:db.execute('UPDATE items SET ultimo_acceso=CURRENT_TIMESTAMP,recent_hidden=0 WHERE drive_id=?',(ident,))
            cover_rendered=self._ensure_cover_on_open(profile,ident,path,item_meta.get('ruta_relativa') or '')
            payload=get_player_server().build_player_payload(path,item_meta)
            payload['cover_rendered']=bool(cover_rendered)
            return payload
        if action=='player_epub_chapter':
            from .player_server import get_player_server
            srv=get_player_server()
            ticket=str(p.get('ticket',''))
            entry=srv.get_ticket(ticket)
            if not entry:raise ValueError('Sesión del lector expirada')
            return srv.read_epub_chapter(ticket,entry,int(p.get('index',0)))
        if action=='player_pdf_text':
            from .player_server import get_player_server
            srv=get_player_server()
            ticket=str(p.get('ticket',''))
            entry=srv.get_ticket(ticket)
            if not entry:raise ValueError('Sesión del lector expirada')
            return srv.get_pdf_page_text(ticket,entry,int(p.get('page',0)))
        if action=='player_pdf_search':
            from .player_server import get_player_server
            srv=get_player_server()
            ticket=str(p.get('ticket',''))
            entry=srv.get_ticket(ticket)
            if not entry:raise ValueError('Sesión del lector expirada')
            return srv.search_pdf(ticket,entry,str(p.get('query','')))
        if action=='player_epub_search':
            from .player_server import get_player_server
            srv=get_player_server()
            ticket=str(p.get('ticket',''))
            entry=srv.get_ticket(ticket)
            if not entry:raise ValueError('Sesión del lector expirada')
            return srv.search_epub(ticket,entry,str(p.get('query','')))
        if False:
            return result
        if action=='reveal':
            self._item(db,p['id']); return manager.mostrar_en_explorador(p['id'])
        if action=='set_hidden':
            item=self._item(db,p['id'])
            if type(p.get('hidden')) is not bool: raise ValueError('Visibilidad inválida')
            with db: db.execute('UPDATE items SET oculto=? WHERE id=?',(int(p['hidden']),item['id']))
            return True
        if action=='containers':
            return [dict(r) for r in db.execute("SELECT drive_id,titulo FROM items WHERE tipo='curso' AND container_parent='' AND disponible=1 AND oculto=0 AND perfil_drive=? ORDER BY titulo COLLATE NOCASE",(profile,))]
        if action=='assign_container':
            ids=p.get('ids',[])
            if not isinstance(ids,list): raise ValueError('Selección inválida')
            for ident in ids: self._item(db,ident)
            result=assign_items(db,profile,ids,p.get('container_id'),p.get('name'))
            self._containers.clear();self._container_cache_info.clear()
            return result
        if action=='ungroup_container':
            self._item(db,p['id'])
            result=ungroup_container(db,profile,p['id'])
            self._containers.clear();self._container_cache_info.clear()
            return result
        if action=='import_container':
            if not isinstance(p.get('path'),str): raise ValueError('Carpeta inválida')
            result=import_container_folder(db,profile,p['path'],active_tag=p.get('active_tag'))
            self._containers.clear();self._container_cache_info.clear()
            return result
        if action=='import_file':
            if not isinstance(p.get('path'),str):raise ValueError('Archivo inválido')
            return import_library_file(db,profile,p['path'],thumbnail_dir=None if root_id(db,profile) else self._dir/'portadas_auto',active_tag=p.get('active_tag'))
        if action=='pick_import_folder':
            import tkinter as tk
            from tkinter import filedialog
            root=tk.Tk(); root.withdraw(); root.attributes('-topmost',True)
            try: return filedialog.askdirectory(parent=root,title='Selecciona la carpeta para importar') or None
            finally: root.destroy()
        if action=='delete_item':
            item=self._item(db,p['id'])
            path=manager.ruta_local(item)
            if not path.exists(): path=Path(manager.auto_reparar_ruta(p['id']))
            snapshot=self._capture_deletion(db,path,{p['id']},p['id'] if item['tipo']=='curso' else None)
            result=manager.eliminar_item(p['id'])
            self._remember_deletion(snapshot)
            return result
        if action=='preference':
            key,value=p['key'],str(p['value'])
            if key=='tema' and value not in ('auto','dark','light'): raise ValueError('Tema inválido')
            elif key=='modo' and value not in ('local','web','balisco'): raise ValueError('Modo inválido')
            elif key=='zoom' and not 60<=int(value)<=430: raise ValueError('Zoom inválido')
            elif key=='wallpaper_opacity' and not 0<=int(value)<=100: raise ValueError('Opacidad inválida')
            elif key=='wallpaper_blur' and not 0<=int(value)<=30: raise ValueError('Desenfoque inválido')
            elif key=='container_background_opacity' and not 0<=int(value)<=100: raise ValueError('Opacidad del fondo de contenedores inválida')
            elif key=='container_background_blur' and not 0<=int(value)<=30: raise ValueError('Desenfoque del fondo de contenedores inválido')
            elif key=='show_overlays' and value not in ('true','false'): raise ValueError('Preferencia inválida')
            elif key=='show_recent_titles' and value not in ('true','false'): raise ValueError('Preferencia inválida')
            elif key=='confirm_delete' and value not in ('true','false'): raise ValueError('Preferencia inválida')
            elif key=='wallpaper': pass
            elif key not in ('tema','modo','zoom','wallpaper','wallpaper_opacity','wallpaper_blur','container_wallpaper','container_background_opacity','container_background_blur','confirm_delete','show_recent_titles'): raise ValueError('Preferencia inválida')
            with db: configurar(db,key,value)
            return True
        if action=='wallpapers_list':
            dirs=[self._dir/'wallpapers', Path(__file__).parent.parent/'wallpapers']
            positions=json.loads(preferencia(db,'wallpaper_positions','{}'))
            found=[]; seen=set()
            for d in dirs:
                if d.is_dir():
                    for f in sorted(d.iterdir()):
                        if f.is_file() and f.suffix.lower() in ('.jpg','.jpeg','.png','.webp') and f.name not in seen:
                            seen.add(f.name)
                            found.append({'name':f.stem.replace('_',' '),'filename':f.name,'size':f.stat().st_size,'centered':positions.get(f.name,True),'removable':d==self._dir/'wallpapers'})
            return found
        if action=='set_wallpaper_centered':
            filename=p.get('filename','')
            if not isinstance(filename,str) or filename!=Path(filename).name or not filename:
                raise ValueError('Fondo inválido')
            dirs=[self._dir/'wallpapers',Path(__file__).parent.parent/'wallpapers']
            if not any((d/filename).is_file() and not (d/filename).is_symlink() for d in dirs):
                raise FileNotFoundError('Fondo no encontrado')
            centered=p.get('centered')
            if not isinstance(centered,bool): raise ValueError('Posición inválida')
            positions=json.loads(preferencia(db,'wallpaper_positions','{}'))
            positions[filename]=centered
            with db: configurar(db,'wallpaper_positions',json.dumps(positions))
            return centered
        if action=='delete_wallpaper':
            filename=p.get('filename','')
            if not isinstance(filename,str) or filename!=Path(filename).name or Path(filename).suffix.lower() not in ('.jpg','.jpeg','.png','.webp'):
                raise ValueError('Fondo inválido')
            target=self._dir/'wallpapers'/filename
            if not target.is_file() or target.is_symlink(): raise FileNotFoundError('Fondo personal no encontrado')
            target.unlink()
            positions=json.loads(preferencia(db,'wallpaper_positions','{}'))
            positions.pop(filename,None)
            active=preferencia(db,'wallpaper','')==filename
            active_container=preferencia(db,'container_wallpaper','')==filename
            with db:
                configurar(db,'wallpaper_positions',json.dumps(positions))
                if active: configurar(db,'wallpaper','')
                if active_container: configurar(db,'container_wallpaper','')
            return {'active':active,'activeContainer':active_container}
        if action=='get_wallpaper':
            fn=p.get('filename')
            if not fn: return None
            fn=Path(fn).name
            thumb=bool(p.get('thumb'))
            dirs=[self._dir/'wallpapers', Path(__file__).parent.parent/'wallpapers']
            for d in dirs:
                f=d/fn
                if f.is_file() and not f.is_symlink():
                    if thumb:
                        try:
                            from PIL import Image, ImageOps
                            with Image.open(f) as img:
                                img=ImageOps.exif_transpose(img).convert('RGB')
                                img.thumbnail((240,150))
                                out=BytesIO()
                                img.save(out,'JPEG',quality=75)
                                return 'data:image/jpeg;base64,'+base64.b64encode(out.getvalue()).decode('ascii')
                        except Exception: pass
                    from PIL import Image, ImageOps
                    try:
                        with Image.open(f) as img:
                            img = ImageOps.exif_transpose(img).convert('RGB')
                            if img.width > 2560 or img.height > 1600:
                                img.thumbnail((2560, 1600), Image.Resampling.LANCZOS)
                            out = BytesIO()
                            img.save(out, 'JPEG', quality=88, optimize=True)
                            return 'data:image/jpeg;base64,' + base64.b64encode(out.getvalue()).decode('ascii')
                    except Exception:
                        mime = 'image/png' if f.suffix.lower() == '.png' else ('image/webp' if f.suffix.lower() == '.webp' else 'image/jpeg')
                        return f'data:{mime};base64,' + base64.b64encode(f.read_bytes()).decode('ascii')
            return None
        if action=='save_wallpaper':
            data=p.get('data')
            name=p.get('name','wallpaper.jpg')
            if not data: raise ValueError('Sin datos')
            clean=''.join(c for c in Path(name).name if c.isalnum() or c in ('_','-','.'))
            if not clean: clean=f'wp_{int(time.time())}.jpg'
            from PIL import Image, ImageOps
            raw=base64.b64decode(data,validate=True)
            with Image.open(BytesIO(raw)) as image:
                image=ImageOps.exif_transpose(image).convert('RGB')
                if image.width>2560 or image.height>1600: image.thumbnail((2560,1600))
                wp_dir=self._dir/'wallpapers'; wp_dir.mkdir(exist_ok=True)
                target=wp_dir/clean
                image.save(target,'JPEG',quality=90)
                return {'filename':clean,'name':target.stem}
        if action=='pick_wallpaper':
            selected=None
            win=getattr(self,'_window',None)
            if win and hasattr(win,'create_file_dialog'):
                try:
                    import webview
                    files=win.create_file_dialog(webview.OPEN_DIALOG,allow_multiple=False,file_types=('Imagenes (*.jpg;*.jpeg;*.png;*.webp)','Todos los archivos (*.*)'))
                    if files and len(files)>0:
                        selected=files[0]
                except Exception: selected=None
            if not selected:
                try:
                    import tkinter as tk
                    from tkinter import filedialog
                    root=tk.Tk(); root.withdraw(); root.attributes('-topmost',True)
                    try: selected=filedialog.askopenfilename(parent=root,title='Selecciona fondo de pantalla',filetypes=[('Imagenes','*.jpg;*.jpeg;*.png;*.webp'),('Todos los archivos','*.*')]) or None
                    finally: root.destroy()
                except Exception: selected=None
            if not selected:
                return None
            path=Path(selected)
            if not path.is_file():
                raise FileNotFoundError('Archivo no encontrado')
            clean=''.join(c for c in path.name if c.isalnum() or c in ('_','-','.'))
            if not clean: clean=f'wp_{int(time.time())}.jpg'
            from PIL import Image, ImageOps
            raw=path.read_bytes()
            with Image.open(BytesIO(raw)) as image:
                image=ImageOps.exif_transpose(image).convert('RGB')
                if image.width>2560 or image.height>1600: image.thumbnail((2560,1600))
                wp_dir=self._dir/'wallpapers'; wp_dir.mkdir(exist_ok=True)
                target=wp_dir/clean
                image.save(target,'JPEG',quality=90)
                with db: configurar(db,'wallpaper',clean)
                return {'filename':clean,'name':target.stem}
        if action=='cover':
            item=self._item(db,p['id']); path=self._dir/'portadas'/(p['id']+'.jpg')
            if not ID_PATTERN.fullmatch(p['id']): raise ValueError('ID inválido')
            if not path.is_file() or path.is_symlink():
                from .thumbnailer import thumbnail_name
                path=self._dir/'portadas_auto'/thumbnail_name(item['perfil_drive'],item['ruta_relativa'])
            if not path.is_file() or path.is_symlink(): return None
            if path.stat().st_size>8_000_000: return None
            return 'data:image/jpeg;base64,'+base64.b64encode(path.read_bytes()).decode('ascii')
        if action=='save_cover':
            ident=p['id']
            if not ID_PATTERN.fullmatch(ident): raise ValueError('ID inválido')
            if p.get('container'): self._item(db,p['container'])
            else: self._item(db,ident)
            if len(p['data'])>12_000_000: raise ValueError('Imagen demasiado grande')
            from PIL import Image, ImageOps
            raw=base64.b64decode(p['data'],validate=True)
            with Image.open(BytesIO(raw)) as image:
                if image.format not in ('JPEG','PNG','WEBP'): raise ValueError('Usa JPG, PNG o WEBP')
                if image.width*image.height>30_000_000: raise ValueError('Imagen demasiado grande')
                image=ImageOps.exif_transpose(image).convert('RGB'); image.thumbnail((600,800), Image.Resampling.LANCZOS)
                covers=self._dir/'portadas'; covers.mkdir(exist_ok=True)
                temp=covers/(ident+'.tmp'); image.save(temp,'JPEG',quality=82,optimize=True,progressive=True)
                os.replace(temp,covers/(ident+'.jpg'))
                self._invalidate_cover_cache()
            return True
        if action=='get_languages':
            row=db.execute("SELECT valor FROM configuracion WHERE clave='idiomas'").fetchone()
            langs=json.loads(row['valor']) if row and row['valor'] else ['Español', 'Inglés']
            return {'languages':langs}
        if action=='add_language':
            name=str(p.get('name','')).strip()
            if not name: raise ValueError('El nombre del idioma no puede estar vacío')
            row=db.execute("SELECT valor FROM configuracion WHERE clave='idiomas'").fetchone()
            langs=json.loads(row['valor']) if row and row['valor'] else ['Español', 'Inglés']
            if not any(l.casefold()==name.casefold() for l in langs):
                langs.append(name)
                with db: db.execute("INSERT INTO configuracion(clave, valor) VALUES('idiomas', ?) ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",(json.dumps(langs),))
            return {'languages':langs}
        if action=='delete_language':
            name=str(p.get('name','')).strip()
            row=db.execute("SELECT valor FROM configuracion WHERE clave='idiomas'").fetchone()
            langs=json.loads(row['valor']) if row and row['valor'] else ['Español', 'Inglés']
            langs=[l for l in langs if l.casefold()!=name.casefold()]
            with db: db.execute("INSERT INTO configuracion(clave, valor) VALUES('idiomas', ?) ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",(json.dumps(langs),))
            return {'languages':langs}
        if action=='delete_cover':
            ident=p['id']
            if not ID_PATTERN.fullmatch(ident): raise ValueError('ID inválido')
            custom=self._dir/'portadas'/(ident+'.jpg')
            if custom.is_file(): custom.unlink()
            if p.get('container'):
                try:
                    container=self._item(db,p['container'])
                    record=self._containers.get(p['container'],{}).get(ident)
                    if record and not record.get('folder'):
                        from .thumbnailer import thumbnail_name
                        auto=self._dir/'portadas_auto'/thumbnail_name(container['perfil_drive'],record['path'])
                        if auto.is_file(): auto.unlink()
                except Exception: pass
            else:
                try:
                    item=self._item(db,ident)
                    from .thumbnailer import thumbnail_name
                    auto=self._dir/'portadas_auto'/thumbnail_name(item['perfil_drive'],item['ruta_relativa'])
                    if auto.is_file(): auto.unlink()
                except Exception: pass
            self._invalidate_cover_cache()
            return True
        if action=='sync':
            with self._sync_lock:result=DriveSync(db).sincronizar_biblioteca(perfil=profile or None)
            DriveSync(db).exportar_libros(self._dir/'export_libros.json'); self._containers.clear(); self._container_cache_info.clear(); self._profile_sources=None; self._invalidate_cover_cache(); return result
        if action=='profiles': return detectar_perfiles_drive()
        if action=='profile':
            if self._storage:
                if not any(entry['id']==p['id'] and not entry.get('error') for entry in detectar_perfiles_drive()):
                    raise ValueError('Cuenta de Drive no disponible')
                with self._imports_lock:
                    if any(job.get('state')=='running' for job in self._imports.values()):
                        raise ValueError('Espera a que termine o cancela la carga antes de cambiar de cuenta')
                with self._sync_lock:self._open_active_profile(p['id'])
            else:
                cambiar_perfil_activo(p['id'],db)
                self._containers.clear();self._container_cache_info.clear();self._profile_sources=None;self._invalidate_cover_cache()
            return True
        if action=='backup':
            return crear_backup_en_biblioteca(library_root(db,profile),db,self._dir)
        if action=='backup_list':
            folder=library_root(db,profile)/('.balisco/backups' if root_id(db,profile) else '.balisco_backup')
            if not folder.is_dir(): return []
            return [{'name':file.name,'size':file.stat().st_size} for file in sorted(folder.glob('Balisco_Backup_*.zip'),reverse=True) if file.is_file() and not file.is_symlink()]
        if action=='backup_reveal':
            name=Path(str(p.get('name',''))).name
            if not name.startswith('Balisco_Backup_') or not name.endswith('.zip'): raise ValueError('Respaldo inválido')
            path=library_root(db,profile)/('.balisco/backups' if root_id(db,profile) else '.balisco_backup')/name
            if not path.is_file() or path.is_symlink(): raise FileNotFoundError('Respaldo ausente')
            import subprocess
            subprocess.Popen(['explorer.exe','/select,',str(path)])
            return True
        if action=='container':
            item=self._item(db,p['id'])
            if item['tipo']!='curso': raise ValueError('No es un contenedor')
            with db:db.execute('UPDATE items SET ultimo_acceso=CURRENT_TIMESTAMP WHERE id=?',(item['id'],))
            if self._profile_sources is None:
                self._profile_sources={row['id']:row['ruta_db'] for row in detectar_perfiles_drive() if row.get('ruta_db')}
            source=self._profile_sources.get(profile)
            if not source: raise FileNotFoundError('Perfil DriveFS no disponible')
            def signature(path):
                try:
                    stat=Path(path).stat();return stat.st_mtime_ns,stat.st_size
                except OSError:return None
            source_signature=(signature(source),signature(str(source)+'-wal'))
            cached=self._container_cache_info.get(p['id'])
            if cached==source_signature and p['id'] in self._containers:
                return self._container_payload(db,p['id'],profile)
            with closing(conectar_db_drive_ro(source)) as conn:
                conn.execute('BEGIN'); meta=Metadata(conn)
            root=None
            for ident,node in meta.nodes.items():
                try:
                    if extraer_ids_proto(node['proto'])[0]==p['id']: root=ident; break
                except (ValueError,UnicodeError): continue
            if root is None: raise FileNotFoundError('Contenedor ausente de DriveFS')
            rootparts=meta.parts(root); records=[]; stack=list(meta.children.get(root,[])); seen=set()
            while stack:
                ident=stack.pop()
                if ident in seen: continue
                seen.add(ident); node=meta.nodes.get(ident); parts=meta.parts(ident)
                if not node or not parts or not rootparts or parts[:len(rootparts)]!=rootparts: continue
                if node['is_folder']:
                    try: folder_id,_=extraer_ids_proto(node['proto'])
                    except (ValueError,UnicodeError): folder_id=None
                    if folder_id:
                        records.append({'id':folder_id,'title':'/'.join(parts[len(rootparts):]),'size':0,
                                        'path':str(PureWindowsPath(*parts)),'mime':node['mime_type'],'folder':True})
                    stack.extend(meta.children.get(ident,[])); continue
                try: drive_id,_=extraer_ids_proto(node['proto'])
                except (ValueError,UnicodeError): continue
                records.append({'id':drive_id,'title':'/'.join(parts[len(rootparts):]),'size':node['file_size'] or 0,'path':str(PureWindowsPath(*parts)),'mime':node['mime_type']})
            folder_sizes={}
            for record in records:
                if record.get('folder'):continue
                parts=record['title'].casefold().split('/')
                for depth in range(1,len(parts)):
                    key='/'.join(parts[:depth]);folder_sizes[key]=folder_sizes.get(key,0)+record['size']
            for folder in (record for record in records if record.get('folder')):
                folder['size']=folder_sizes.get(folder['title'].casefold(),0)
            # Materialize only entries confirmed by DriveFS. Their Drive IDs preserve personal metadata.
            existing={row['drive_id']:row for row in db.execute('''SELECT drive_id,titulo,titulo_personalizado,tipo,tipo_contenido,formato,
                categoria_macro,ruta_relativa,tamano_bytes,mime_type,disponible FROM items
                WHERE container_parent=? AND perfil_drive=?''',(item['drive_id'],profile))}
            container_category=item['categoria_macro'] if root_id(db,profile) else 'Containers'
            changed=[]
            for record in records:
                filename=PureWindowsPath(record['path']).name
                folder=bool(record.get('folder'))
                kind='curso' if folder else (classify_file(filename,allow_other=True) or 'archivo')
                content='contenedor' if folder else 'documento' if kind=='pdf' else 'otro' if kind=='archivo' else kind
                title=filename if folder else clean_book_title_and_author(filename,kind)[0] if kind=='pdf' else Path(filename).stem
                fmt='' if folder else Path(filename).suffix.lstrip('.').upper()
                old=existing.get(record['id'])
                if old and old['disponible'] and old['tipo']==kind and old['tipo_contenido']==content and old['formato']==fmt and old['categoria_macro']==container_category and old['ruta_relativa']==record['path'] and old['tamano_bytes']==record['size'] and old['mime_type']==record['mime'] and (old['titulo_personalizado'] or old['titulo']==title):
                    continue
                changed.append((record['id'],title,'',kind,content,fmt,container_category,record['path'],
                                'portadas/'+record['id']+'.jpg',record['size'],record['mime'],profile,item['drive_id']))
            with db:
                db.executemany('''INSERT INTO items(drive_id,titulo,autor,tipo,tipo_contenido,formato,categoria_macro,
                        ruta_relativa,ruta_portada,tamano_bytes,mime_type,perfil_drive,disponible,container_parent)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,?) ON CONFLICT(drive_id) DO UPDATE SET
                        titulo=CASE WHEN items.titulo_personalizado=1 THEN items.titulo ELSE excluded.titulo END,
                        tipo=excluded.tipo,tipo_contenido=excluded.tipo_contenido,formato=excluded.formato,
                        categoria_macro=excluded.categoria_macro,ruta_relativa=excluded.ruta_relativa,
                        tamano_bytes=excluded.tamano_bytes,mime_type=excluded.mime_type,
                        perfil_drive=excluded.perfil_drive,disponible=1,container_parent=excluded.container_parent''',changed)
            known={record['id'] for record in records}
            root_parts=PureWindowsPath(item['ruta_relativa']).parts
            for entry in db.execute('''SELECT drive_id,titulo,ruta_relativa,tamano_bytes,mime_type FROM container_entries
                WHERE container_drive_id=? AND perfil_drive=?''',(item['drive_id'],profile)):
                if entry['drive_id'] in known:continue
                path=manager.ruta_local(dict(item,ruta_relativa=entry['ruta_relativa']))
                if not path.is_file():continue
                parts=PureWindowsPath(entry['ruta_relativa']).parts
                title='/'.join(parts[len(root_parts):]) if parts[:len(root_parts)]==root_parts else entry['titulo']
                records.append({'id':entry['drive_id'],'title':title,'size':entry['tamano_bytes'],
                                'path':entry['ruta_relativa'],'mime':entry['mime_type']})
                with db:db.execute('''UPDATE items SET disponible=1,container_parent=?,ruta_relativa=?
                    WHERE drive_id=? AND perfil_drive=?''',(item['drive_id'],entry['ruta_relativa'],entry['drive_id'],profile))
            records.sort(key=lambda r:r['title'].casefold())
            self._containers[p['id']]={r['id']:r for r in records}
            self._container_cache_info[p['id']]=source_signature
            return self._container_payload(db,p['id'],profile)
        if action=='container_view':
            item=self._item(db,p['id'])
            if item['tipo']!='curso': raise ValueError('No es un contenedor')
            key='vista_contenedor_v2:'+item['drive_id']
            view=p.get('view')
            if view is not None:
                if view not in ('details','list','grid'): raise ValueError('Vista de contenedor inválida')
                with db: configurar(db,key,view)
            saved=preferencia(db,key,'')
            if not saved:
                legacy=preferencia(db,'vista_contenedor:'+item['drive_id'],'list')
                saved='grid' if legacy=='grid' else 'details'
            return {'view':saved if saved in ('details','list','grid') else 'details'}
        if action=='container_cover':
            container=self._item(db,p['container'])
            if container['tipo']!='curso': raise ValueError('No es un contenedor')
            ident=str(p.get('id',''))
            if not ID_PATTERN.fullmatch(ident): raise ValueError('ID inválido')
            record=self._containers.get(p['container'],{}).get(ident)
            if not record or record.get('folder'): return None
            path=self._dir/'portadas'/(ident+'.jpg')
            if not path.is_file() or path.is_symlink():
                from .thumbnailer import thumbnail_name
                path=self._dir/'portadas_auto'/thumbnail_name(container['perfil_drive'],record['path'])
            if not path.is_file() or path.is_symlink() or path.stat().st_size>8_000_000: return None
            return 'data:image/jpeg;base64,'+base64.b64encode(path.read_bytes()).decode('ascii')
        if action=='container_resource_detail':
            container=self._item(db,p['container'])
            if p['container'] not in self._containers:
                self._dispatch(db,'container',{'id':p['container']})
            record=self._containers.get(p['container'],{}).get(p['id'])
            if not record: raise ValueError('Vuelve a cargar el contenedor')
            result={key:record.get(key) for key in ('id','title','size','mime','folder')}
            result['item']=None
            item=db.execute('SELECT * FROM items WHERE drive_id=? AND perfil_drive=? AND disponible=1',
                            (p['id'],container['perfil_drive'])).fetchone()
            if item: result['item']=dict(item)
            return result
        if action=='container_indexed_ids':
            container=self._item(db,p['container'])
            if container['tipo']!='curso': raise ValueError('No es un contenedor')
            ids=p.get('ids',[])
            if not isinstance(ids,list) or len(ids)>10000 or any(not isinstance(ident,str) or not ID_PATTERN.fullmatch(ident) for ident in ids):
                raise ValueError('Selección inválida')
            records=self._containers.get(p['container'])
            if records is None:
                self._dispatch(db,'container',{'id':p['container']})
                records=self._containers.get(p['container'],{})
            allowed=[ident for ident in dict.fromkeys(ids) if ident in records]
            indexed=[]
            for start in range(0,len(allowed),900):
                chunk=allowed[start:start+900]
                indexed.extend(row[0] for row in db.execute(
                    'SELECT drive_id FROM items WHERE perfil_drive=? AND disponible=1 AND drive_id IN ('+','.join('?' for _ in chunk)+')',
                    (container['perfil_drive'],*chunk)))
            return indexed
        if action=='container_update':
            container=self._item(db,p['container'])
            if container['tipo']!='curso': raise ValueError('No es un contenedor')
            ident=str(p.get('id',''));field=p.get('field');value=p.get('value')
            allowed={'es_favorito','rating','estado_lectura','oculto','mostrar_en_filtros','titulo'}
            if field not in allowed: raise ValueError('Propiedad del recurso no permitida')
            record=self._containers.get(p['container'],{}).get(ident)
            if not record:
                self._dispatch(db,'container',{'id':p['container']})
                record=self._containers.get(p['container'],{}).get(ident)
            if not record: raise ValueError('El recurso ya no está en este contenedor')
            if field=='titulo':
                if not isinstance(value,str) or not value.strip(): raise ValueError('Título no válido')
                val=value.strip()
                with db:
                    updated=db.execute('UPDATE items SET titulo=?,titulo_personalizado=1 WHERE drive_id=? AND perfil_drive=?',
                                       (val,ident,profile)).rowcount
                if not updated: raise ValueError('Este archivo todavía no tiene propiedades de biblioteca')
                if record: record['title']=val
                return {'field':'titulo','value':val}
            record=self._containers.get(p['container'],{}).get(ident)
            if not record:
                self._dispatch(db,'container',{'id':p['container']})
                record=self._containers.get(p['container'],{}).get(ident)
            if not record: raise ValueError('El recurso ya no está en este contenedor')
            if field in ('es_favorito','oculto','mostrar_en_filtros') and type(value) is not bool: raise ValueError('Favorito inválido')
            if field=='rating' and (type(value) is not int or value not in range(6)): raise ValueError('Calificación inválida')
            if field=='estado_lectura' and value not in ('pendiente','interesado','leyendo','leido','abandonado'):
                raise ValueError('Estado de lectura inválido')
            with db:
                updated=db.execute('UPDATE items SET '+field+'=? WHERE drive_id=? AND perfil_drive=?',
                                   (int(value) if field in ('es_favorito','oculto','mostrar_en_filtros') else value,ident,profile)).rowcount
            if not updated: raise ValueError('Este archivo todavía no tiene propiedades de biblioteca')
            return {'field':field,'value':int(value) if field in ('es_favorito','oculto','mostrar_en_filtros') else value}
        if action=='container_move_to_storage':
            container=self._item(db,p['container'])
            self._dispatch(db,'container',{'id':p['container']})
            record=self._containers.get(p['container'],{}).get(p['id'])
            if not record or record.get('folder'): raise ValueError('Selecciona un archivo del contenedor')
            library=library_root(db,profile)
            container_path=manager.ruta_local(container)
            source=inside(manager.ruta_local(dict(container,ruta_relativa=record['path'])),container_path)
            if not source.is_file(): raise FileNotFoundError('El archivo ya no está disponible en el contenedor')
            filename=PureWindowsPath(record['path']).name
            if root_id(db,profile):
                result=extract_to_library(db,profile,container,[source])
                self._containers.get(p['container'],{}).pop(p['id'],None)
                return {'id':p['id'],'title':filename,'path':relative_path(db,profile,result['paths'][0],library)}
            linked=bool(root_id(db,profile))
            storage=container_path.parent if linked else library/'Storage';storage.mkdir(exist_ok=True)
            target=inside(storage/filename,library)
            if target.exists(): raise FileExistsError('Ya existe un archivo con ese nombre en Storage')
            shutil.move(str(source),str(target))
            ext=target.suffix.casefold()
            tipo=classify_file(filename,allow_other=True)
            tipo_contenido='documento' if tipo=='pdf' else 'otro' if tipo=='archivo' else tipo
            relative=relative_path(db,profile,target,library) if linked else str(PureWindowsPath(library.parent.name,'Biblioteca','Storage',filename))
            try:
                with db:
                    item=db.execute('SELECT id FROM items WHERE drive_id=? AND perfil_drive=?',(p['id'],profile)).fetchone()
                    if item:
                        db.execute('''UPDATE items SET tipo=?,tipo_contenido=?,formato=?,categoria_macro=?,
                            subcategoria='',ruta_relativa=?,tamano_bytes=?,mime_type=?,disponible=1,container_parent='' WHERE id=?''',
                            (tipo,tipo_contenido,ext.lstrip('.').upper(),storage.name,relative,target.stat().st_size,record.get('mime'),item['id']))
                    else:
                        title,author=clean_book_title_and_author(filename,tipo) if tipo=='pdf' else (target.stem,'')
                        db.execute('''INSERT INTO items(drive_id,titulo,autor,tipo,tipo_contenido,formato,categoria_macro,
                            ruta_relativa,ruta_portada,tamano_bytes,mime_type,perfil_drive,disponible)
                            VALUES(?,?,?,?,?,?, ?,?,?,?, ?,?,1)''',
                            (p['id'],title,author,tipo,tipo_contenido,ext.lstrip('.').upper(),storage.name,relative,
                             'portadas/'+p['id']+'.jpg',target.stat().st_size,record.get('mime'),profile))
                    db.execute('DELETE FROM container_entries WHERE drive_id=? AND container_drive_id=?',(p['id'],p['container']))
                    db.execute('''INSERT INTO pending_container_moves(drive_id,expected_relative,container_drive_id,perfil_drive)
                        VALUES(?,?,'',?) ON CONFLICT(drive_id) DO UPDATE SET expected_relative=excluded.expected_relative,
                        container_drive_id='',perfil_drive=excluded.perfil_drive,created_at=CURRENT_TIMESTAMP''',
                        (p['id'],relative,profile))
            except Exception:
                shutil.move(str(target),str(source))
                raise
            self._containers.get(p['container'],{}).pop(p['id'],None)
            if linked:cleanup_category(source.parent)
            return {'id':p['id'],'title':filename,'path':relative}
        if action=='container_move_folder_to_storage':
            container=self._item(db,p['container'])
            parts=p.get('path')
            if not isinstance(parts,list) or not parts or any(not isinstance(part,str) or not part.strip() or part.strip() in ('.','..') or '/' in part or '\\' in part for part in parts):
                raise ValueError('Ruta de carpeta inválida')
            self._dispatch(db,'container',{'id':p['container']})
            folder='/'.join(part.strip() for part in parts);prefix=folder.casefold()+'/'
            records=self._containers.get(p['container'],{})
            files=[row for row in records.values() if not row.get('folder') and row.get('title','').replace('\\','/').casefold().startswith(prefix)]
            if not files: raise ValueError('La carpeta no contiene archivos para mover')
            library=library_root(db,profile);container_path=manager.ruta_local(container)
            source=inside(manager.ruta_local(dict(container,ruta_relativa=str(PureWindowsPath(container['ruta_relativa'],*parts)))),container_path)
            if not source.is_dir(): raise FileNotFoundError('La carpeta ya no está disponible')
            if root_id(db,profile):
                result=extract_to_library(db,profile,container,[source])
                for record in list(records.values()):
                    if record.get('title','').replace('\\','/').casefold()==folder.casefold() or record.get('title','').replace('\\','/').casefold().startswith(prefix):
                        records.pop(record['id'],None)
                return {'title':parts[-1],'moved':len(files),'path':relative_path(db,profile,result['paths'][0],library)}
            linked=bool(root_id(db,profile))
            storage=container_path.parent if linked else library/'Storage';storage.mkdir(exist_ok=True)
            target=inside(storage/parts[-1],library)
            if target.exists(): raise FileExistsError('Ya existe una carpeta con ese nombre en Storage')
            shutil.move(str(source),str(target))
            try:
                with db:
                    for record in files:
                        relative_parts=record['title'].replace('\\','/').split('/')[len(parts):]
                        destination=target.joinpath(*relative_parts)
                        ext=destination.suffix.casefold();tipo=classify_file(destination.name,allow_other=True)
                        tipo_contenido='documento' if tipo=='pdf' else 'otro' if tipo=='archivo' else tipo
                        relative=relative_path(db,profile,destination,library) if linked else str(PureWindowsPath(library.parent.name,'Biblioteca','Storage',parts[-1],*relative_parts))
                        item=db.execute('SELECT id FROM items WHERE drive_id=? AND perfil_drive=?',(record['id'],profile)).fetchone()
                        if item:
                            db.execute('''UPDATE items SET tipo=?,tipo_contenido=?,formato=?,categoria_macro=?,
                                subcategoria='',ruta_relativa=?,tamano_bytes=?,mime_type=?,disponible=1,container_parent='' WHERE id=?''',
                                (tipo,tipo_contenido,ext.lstrip('.').upper(),storage.name,relative,destination.stat().st_size,record.get('mime'),item['id']))
                        else:
                            title,author=clean_book_title_and_author(destination.name,tipo) if tipo=='pdf' else (destination.stem,'')
                            db.execute('''INSERT INTO items(drive_id,titulo,autor,tipo,tipo_contenido,formato,categoria_macro,
                                ruta_relativa,ruta_portada,tamano_bytes,mime_type,perfil_drive,disponible)
                                VALUES(?,?,?,?,?,?, ?,?,?,?, ?,?,1)''',
                                (record['id'],title,author,tipo,tipo_contenido,ext.lstrip('.').upper(),storage.name,relative,
                                 'portadas/'+record['id']+'.jpg',destination.stat().st_size,record.get('mime'),profile))
                        db.execute('DELETE FROM container_entries WHERE drive_id=? AND container_drive_id=?',(record['id'],p['container']))
                        db.execute('''INSERT INTO pending_container_moves(drive_id,expected_relative,container_drive_id,perfil_drive)
                            VALUES(?,?,'',?) ON CONFLICT(drive_id) DO UPDATE SET expected_relative=excluded.expected_relative,
                            container_drive_id='',perfil_drive=excluded.perfil_drive,created_at=CURRENT_TIMESTAMP''',(record['id'],relative,profile))
            except Exception:
                shutil.move(str(target),str(source))
                raise
            for record in list(records.values()):
                if record.get('title','').replace('\\','/').casefold()==folder.casefold() or record.get('title','').replace('\\','/').casefold().startswith(prefix):
                    records.pop(record['id'],None)
            if linked:cleanup_category(source.parent)
            return {'title':parts[-1],'moved':len(files)}
        if action=='container_trash_folder':
            container=self._item(db,p['container'])
            parts=p.get('path')
            if not isinstance(parts,list) or not parts or any(not isinstance(part,str) or not part.strip() or part.strip() in ('.','..') or '/' in part or '\\' in part for part in parts):
                raise ValueError('Ruta de carpeta inválida')
            self._dispatch(db,'container',{'id':p['container']})
            relative='/'.join(part.strip() for part in parts)
            prefix=relative.casefold()+'/'
            if not any(row.get('folder') and row.get('title','').replace('\\','/').casefold()==relative.casefold()
                       for row in self._containers.get(p['container'],{}).values()):
                # Folders inferred from nested files are also valid; the path still has to contain resources.
                if not any(row.get('title','').replace('\\','/').casefold().startswith(prefix)
                           for row in self._containers.get(p['container'],{}).values()):
                    raise FileNotFoundError('No se encontró esa carpeta en el contenedor')
            library=library_root(db,profile)
            container_path=manager.ruta_local(container)
            target=inside(manager.ruta_local(dict(container,ruta_relativa=str(PureWindowsPath(container['ruta_relativa'],*parts)))),container_path)
            if not target.is_dir(): raise FileNotFoundError('La carpeta ya no está disponible')
            ids={row['id'] for row in self._containers.get(p['container'],{}).values()
                 if not row.get('folder') and row.get('title','').replace('\\','/').casefold().startswith(prefix)}
            entry_rows=db.execute('SELECT drive_id,ruta_relativa FROM container_entries WHERE container_drive_id=? AND perfil_drive=?',
                                  (p['container'],profile)).fetchall()
            container_parts=PureWindowsPath(container['ruta_relativa']).parts
            folder_parts=tuple(container_parts)+tuple(parts)
            for row in entry_rows:
                path_parts=PureWindowsPath(row['ruta_relativa']).parts
                if len(path_parts)>len(folder_parts) and all(a.casefold()==b.casefold() for a,b in zip(path_parts,folder_parts)):
                    ids.add(row['drive_id'])
            snapshot=self._capture_deletion(db,target,ids)
            from send2trash import send2trash as send2trash_fn
            send2trash_fn(str(target))
            with db:
                for ident in ids:
                    db.execute('DELETE FROM container_entries WHERE drive_id=? AND container_drive_id=?',(ident,p['container']))
                    db.execute('UPDATE items SET disponible=0 WHERE drive_id=? AND perfil_drive=?',(ident,profile))
                    db.execute('''INSERT INTO pending_container_moves(drive_id,expected_relative,container_drive_id,perfil_drive)
                        VALUES(?,'','__removed__',?) ON CONFLICT(drive_id) DO UPDATE SET expected_relative='',
                        container_drive_id='__removed__',perfil_drive=excluded.perfil_drive,created_at=CURRENT_TIMESTAMP''',(ident,profile))
            for ident in ids: self._containers.get(p['container'],{}).pop(ident,None)
            self._remember_deletion(snapshot)
            return {'deleted':len(ids)}
        if action=='container_reveal':
            container=self._item(db,p['container'])
            if container['tipo']!='curso': raise ValueError('No es un contenedor')
            self._dispatch(db,'container',{'id':p['container']})
            requested=p.get('path',[])
            if not isinstance(requested,list) or any(not isinstance(part,str) or not part.strip() or part.strip() in ('.','..') or '/' in part or '\\' in part for part in requested):
                raise ValueError('Ruta de carpeta inválida')
            if requested:
                wanted='/'.join(part.strip() for part in requested).casefold()
                record=next((row for row in self._containers.get(p['container'],{}).values()
                             if row.get('folder') and row['title'].replace('\\','/').casefold()==wanted),None)
                if not record: raise FileNotFoundError('No se encontró esa subcarpeta en DriveFS')
                target=dict(container,ruta_relativa=record['path'])
            else:
                target=container
            os.startfile(str(manager.ruta_local(target)))
            return True
        if action in ('container_open','container_trash'):
            container=self._item(db,p['container'])
            self._dispatch(db,'container',{'id':p['container']})
            record=self._containers.get(p['container'],{}).get(p['id'])
            if not record: raise ValueError('Vuelve a cargar el contenedor')
            if record.get('folder'): raise ValueError('Abre una carpeta desde la vista del contenedor')
            if action=='container_open' and p.get('mode')=='web':
                try:self._ensure_cover_on_open(profile,p['id'],manager.ruta_local(dict(container,ruta_relativa=record['path'])),record.get('path') or '')
                except Exception:pass
                opened=webbrowser.open('https://drive.google.com/file/d/'+record['id']+'/view')
                with db:db.execute('UPDATE items SET ultimo_acceso=CURRENT_TIMESTAMP,recent_hidden=0 WHERE drive_id=?',(p['id'],))
                return opened
            item=dict(container,ruta_relativa=record['path']); path=manager.ruta_local(item)
            if action=='container_open':
                self._ensure_cover_on_open(profile,p['id'],path,record.get('path') or '')
                os.startfile(str(path))
                with db:db.execute('UPDATE items SET ultimo_acceso=CURRENT_TIMESTAMP,recent_hidden=0 WHERE drive_id=?',(p['id'],))
            else:
                from send2trash import send2trash
                snapshot=self._capture_deletion(db,path,{p['id']})
                send2trash(str(path)); del self._containers[p['container']][p['id']]
                with db:
                    db.execute('DELETE FROM container_entries WHERE drive_id=? AND container_drive_id=?',(p['id'],p['container']))
                    db.execute('UPDATE items SET disponible=0 WHERE drive_id=? AND perfil_drive=?',(p['id'],profile))
                    db.execute('''INSERT INTO pending_container_moves(drive_id,expected_relative,container_drive_id,perfil_drive)
                        VALUES(?,'','__removed__',?) ON CONFLICT(drive_id) DO UPDATE SET expected_relative='',
                        container_drive_id='__removed__',perfil_drive=excluded.perfil_drive,created_at=CURRENT_TIMESTAMP''',(p['id'],profile))
                self._remember_deletion(snapshot)
            return True
        if action=='companion_get':
            from .companion import CompanionEngine
            return CompanionEngine(self._dir/'companion.db').get_state()
        if action=='companion_interact':
            from .companion import CompanionEngine
            engine = CompanionEngine(self._dir/'companion.db')
            tipo = p.get('tipo', 'charla')
            res = engine.update_interaction(tipo)
            if p.get('mensaje'):
                engine.registrar_mensaje('usuario', p['mensaje'])
                if p.get('respuesta'):
                    engine.registrar_mensaje('companion', p['respuesta'], res.get('sprite'), res.get('humor'))
            return res
        if action=='companion_descansar':
            from .companion import CompanionEngine
            CompanionEngine(self._dir/'companion.db').descansar()
            return CompanionEngine(self._dir/'companion.db').get_state()
        raise ValueError('Acción no soportada')
