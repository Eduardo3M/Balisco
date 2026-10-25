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
from .database import DATA_DIR, conectar, configurar, preferencia
from .items_manager import ItemsManager
from .tags_manager import TagsManager, obtener_etiquetas_ordenadas_frecuencia
from .search_parser import agregar_filtro, limpiar_todos_filtros, construir_query_sql, fts_query, internal_searchable
from .serendipity import obtener_aleatorio_puro, obtener_semi_aleatorio_contextual, obtener_similares
from .drive_sync import (DriveSync, Metadata, conectar_db_drive_ro, detectar_perfiles_drive,
                         extraer_ids_proto, ID_PATTERN, obtener_letra_drive, cambiar_perfil_activo, classify_file)
from .backup_manager import crear_backup_en_biblioteca
from .metadata_editor import edit_taxonomy
from .container_ops import (assign_items, ungroup_container, import_container_folder,
                            import_library_file, library_root, inside, ImportCancelled)
from .cleaner import clean_book_title_and_author

class DesktopAPI:
    def __init__(self, data_dir=None, started=None):
        self._dir=Path(data_dir or DATA_DIR)
        self._dbpath=self._dir/'biblioteca.db'
        self._lock=threading.RLock()
        self._sync_lock=threading.RLock()
        self._containers={}
        self._imports={}
        self._imports_lock=threading.RLock()
        self._started=started or time.perf_counter()
        from .migrations import migrate_author
        migrate_author(self._dbpath)
        from .migrations import migrate_interested
        migrate_interested(self._dbpath)
        from .migrations import migrate_legacy_course_items
        migrate_legacy_course_items(self._dbpath)
        from .migrations import migrate_item_file_types
        migrate_item_file_types(self._dbpath)
        with closing(conectar(self._dbpath)) as db:
            if 'autor' not in {r[1] for r in db.execute('PRAGMA table_info(items)')}:
                raise RuntimeError('La base requiere la migración de autor de Fase 1 antes de iniciar.')
    def _connect(self):
        db=sqlite3.connect(self._dbpath,timeout=10)
        db.create_function('unicode_casefold',1,lambda value: str(value or '').casefold(),deterministic=True)
        db.row_factory=sqlite3.Row
        return db
    WINDOW_ACTIONS = frozenset({'close', 'window_minimize', 'window_toggle_maximize',
                                'window_drag', 'window_resize', 'window_state', 'window_snap'})
    def call(self, action, payload=None):
        """Only this method is exposed to JS. Never accept executable SQL or paths."""
        try:
            if action=='import_status':
                with self._imports_lock:
                    job=self._imports.get(str((payload or {}).get('id')))
                    public={key:value for key,value in (job or {'state':'unknown','message':'Importación no encontrada'}).items() if key in {'id','state','phase','kind','name','message','data','error'}}
                    return {'ok':True,'data':public}
            if action=='import_jobs':
                with self._imports_lock:return {'ok':True,'data':[{key:value for key,value in job.items() if key in {'id','state','phase','kind','name','message','error'}} for job in self._imports.values()]}
            if action=='start_import': return {'ok':True,'data':self._start_import((payload or {}).get('path'))}
            if action=='cancel_import': return {'ok':True,'data':self._cancel_import(str((payload or {}).get('id','')))}
            if action=='delete_import': return {'ok':True,'data':self._delete_import(str((payload or {}).get('id','')))}
            if action=='sync':
                with closing(self._connect()) as db:return {'ok':True,'data':self._dispatch(db,action,payload or {})}
            if action in self.WINDOW_ACTIONS:
                return {'ok':True,'data':self._window_action(action,payload or {})}
            with self._lock, closing(self._connect()) as db:
                value=self._dispatch(db,action,payload or {})
            return {'ok':True,'data':value}
        except Exception as exc:
            return {'ok':False,'error':str(exc),'kind':type(exc).__name__}
    def _start_import(self,path):
        from pathlib import Path
        if not isinstance(path,str) or not path.strip():raise ValueError('Selecciona un archivo o carpeta válido')
        candidate=Path(str(path or ''))
        if candidate.is_symlink():raise ValueError('No se pueden importar enlaces simbólicos')
        source=candidate.resolve()
        if not source.exists() or (not source.is_file() and not source.is_dir()):raise ValueError('Selecciona un archivo o carpeta válido')
        ident=uuid.uuid4().hex
        kind='folder' if source.is_dir() else 'file'
        with self._imports_lock:
            finished=[key for key,job in self._imports.items() if job.get('state') in ('done','error')]
            for key in finished[:-49]:self._imports.pop(key,None)
            self._imports[ident]={'id':ident,'state':'running','phase':'preparando','kind':kind,'name':source.name,'message':'Preparando importación'}
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
            expected_parent=(library/('Containers' if kind=='folder' else 'Storage')).resolve()
            if target.parent.resolve()!=expected_parent:raise ValueError('No se pudo verificar la ruta de la copia cancelada')
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
        relative=str(PureWindowsPath(library.parent.name,'Biblioteca','Containers' if kind=='folder' else 'Storage',target.name))
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
                    row=db.execute('SELECT drive_id FROM items WHERE ruta_relativa=? AND perfil_drive=?',(relative,profile)).fetchone()
                    drive_id=job.get('drive_id') or (row['drive_id'] if row else None)
                    if drive_id:
                        db.execute('''INSERT INTO pending_container_moves(drive_id,expected_relative,container_drive_id,perfil_drive)
                            VALUES(?,'','__removed__',?) ON CONFLICT(drive_id) DO UPDATE SET
                            expected_relative='',container_drive_id='__removed__',created_at=CURRENT_TIMESTAMP''',(drive_id,profile))
                        db.execute('DELETE FROM items WHERE drive_id=?',(drive_id,))
                    db.execute('DELETE FROM items WHERE ruta_relativa=? AND perfil_drive=?',(relative,profile))
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
                if cancelled():raise ImportCancelled()
                if kind=='folder':
                    data=import_container_folder(db,profile,str(source),progress=progress,cancelled=cancelled,on_target=on_target)
                else:
                    data=import_library_file(db,profile,str(source),progress=progress,cancelled=cancelled,on_target=on_target,
                                             thumbnail_dir=self._dir/'portadas_auto')
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
        if action=='window_state': return {'maximized':chrome.is_maximized()}
        if action=='window_drag': return chrome.drag(float(p.get('rx',0.5)),int(p.get('oy',20)))
        if action=='window_snap': return chrome.snap()
        if action=='window_resize': return chrome.resize(str(p.get('edge','')))
        return None
    def _item(self,db,ident):
        item=ItemsManager(db).obtener(ident)
        if item['perfil_drive']!=preferencia(db,'id_perfil_drive','') or not item['disponible']:
            raise ValueError('Elemento fuera del perfil activo')
        return item
    def _internal_searchable(self,db,item,cache):
        return internal_searchable(db,item,cache)
    def _dispatch(self,db,action,p):
        profile=preferencia(db,'id_perfil_drive','')
        manager=ItemsManager(db)
        if action=='bootstrap':
            return {'prefs':{r['clave']:r['valor'] for r in db.execute("SELECT * FROM configuracion WHERE clave IN ('tema','zoom','modo','id_perfil_drive','wallpaper','wallpaper_opacity','wallpaper_blur','wallpaper_positions','container_wallpaper','container_background_opacity','container_background_blur')")},'count':db.execute("SELECT count(*) FROM items WHERE disponible=1 AND oculto=0 AND container_parent='' AND perfil_drive=?",(profile,)).fetchone()[0]}
        if action=='ready':
            metrics={'ready_ms':round((time.perf_counter()-self._started)*1000,1),'renderer':'edgechromium','frontend':p}
            (self._dir/'performance.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
            return metrics
        if action=='query':
            filters=limpiar_todos_filtros()
            for token in p.get('tokens',[]): filters=agregar_filtro(str(token),filters)
            sql,args=construir_query_sql(filters,profile)
            sql=sql.replace('SELECT i.*','SELECT i.drive_id,i.titulo,i.autor,i.tipo,i.tipo_contenido,i.formato,i.estado_lectura,i.es_favorito,i.rating,i.tamano_bytes,i.categoria_macro,i.indexar_contenido,i.oculto,i.container_parent,i.fijado,i.search_override,i.ruta_relativa')
            items=[dict(r) for r in db.execute(sql,args)]
            terms=[fts_query(p['valor']) for p in filters['pildoras'] if p['tipo']=='texto_titulo']
            if terms:
                cache={}
                items=[item for item in items if self._internal_searchable(db,item,cache)]
            if terms:
                for item in items:
                    if item['tipo']=='curso' and item['indexar_contenido']:
                        matches=[]
                        for term in terms:
                            matches.extend(r[0] for r in db.execute('''SELECT e.titulo FROM container_entries e
                                JOIN container_entries_fts f ON f.rowid=e.id
                                WHERE e.container_drive_id=? AND container_entries_fts MATCH ? LIMIT 3''',
                                (item['drive_id'],term)))
                        item['coincidencia_interna']=list(dict.fromkeys(matches))[:3]
            total=db.execute("SELECT count(*) FROM items WHERE perfil_drive=? AND disponible=1 AND oculto=0 AND container_parent=''",(profile,)).fetchone()[0]
            return {'items':items,'total':total,'filters':filters['pildoras']}
        if action=='set_deep_search':
            item=self._item(db,p['id'])
            if item['tipo']!='curso' or type(p.get('enabled')) is not bool:
                raise ValueError('Configuración del contenedor inválida')
            enabled=int(p['enabled'])
            try:
                self._dispatch(db,'container',{'id':item['drive_id']})
                records=list(self._containers.get(item['drive_id'],{}).values())
            except FileNotFoundError:
                # Let the existing catalog snapshot remain searchable when DriveFS is temporarily unavailable.
                records=[{'id':row['drive_id'],'title':row['titulo'],'path':row['ruta_relativa'],
                          'size':row['tamano_bytes'],'mime':row['mime_type']}
                         for row in db.execute('''SELECT drive_id,titulo,ruta_relativa,tamano_bytes,mime_type
                             FROM container_entries WHERE container_drive_id=? AND perfil_drive=?''',
                             (item['drive_id'],profile))]
            with db:
                db.execute('DELETE FROM container_entries WHERE container_drive_id=? AND perfil_drive=?',(item['drive_id'],profile))
                db.execute('UPDATE items SET indexar_contenido=? WHERE id=?',(enabled,item['id']))
                db.executemany('''INSERT INTO container_entries(container_drive_id,drive_id,titulo,ruta_relativa,tamano_bytes,mime_type,perfil_drive)
                    VALUES(?,?,?,?,?,?,?) ON CONFLICT(drive_id) DO UPDATE SET
                    container_drive_id=excluded.container_drive_id,titulo=excluded.titulo,
                    ruta_relativa=excluded.ruta_relativa,tamano_bytes=excluded.tamano_bytes,
                    mime_type=excluded.mime_type,perfil_drive=excluded.perfil_drive''',
                    [(item['drive_id'],row['id'],row['title'],row['path'],row.get('size') or 0,row.get('mime'),profile)
                     for row in records if not row.get('folder')])
            return {'indexar_contenido':int(p['enabled'])}
        if action=='detail':
            item=self._item(db,p['id']); item['url']=manager.url(p['id']); return item
        if action=='update':
            self._item(db,p['id'])
            methods={'titulo':manager.cambiar_titulo,'autor':manager.cambiar_autor,'notas':manager.actualizar_notas,'rating':manager.cambiar_rating,'estado_lectura':manager.cambiar_estado_lectura,'es_favorito':manager.cambiar_favorito,'etiquetas':TagsManager(db).actualizar_etiquetas_item}
            if p['field'] not in methods: raise ValueError('Campo no editable')
            methods[p['field']](p['id'],p['value']); return self._item(db,p['id'])
        if action=='bulk_update':
            ids=p.get('ids');field=p.get('field');value=p.get('value')
            if not isinstance(ids,list) or not ids or len(ids)>10000 or len(ids)!=len(set(ids)):
                raise ValueError('Selección inválida')
            if field in ('es_favorito','fijado') and type(value) is bool:value=int(value)
            elif field=='rating' and type(value) is int and value in range(6):pass
            elif field=='estado_lectura' and value in ('pendiente','interesado','leyendo','leido','abandonado'):pass
            else:raise ValueError('Cambio masivo inválido')
            items=[self._item(db,ident) for ident in ids]
            with db:db.executemany('UPDATE items SET '+field+'=? WHERE id=?',[(value,item['id']) for item in items])
            return {'updated':len(items)}
        if action=='set_search_override':
            ids=p.get('ids');value=p.get('value')
            if not isinstance(ids,list) or not ids or len(ids)>10000 or len(ids)!=len(set(ids)) or type(value) is not int or value not in (-1,0,1):
                raise ValueError('Selección de búsqueda inválida')
            items=[self._item(db,ident) for ident in ids]
            if any(not item['container_parent'] for item in items):raise ValueError('Selecciona contenido de un contenedor')
            with db:db.executemany('UPDATE items SET search_override=? WHERE id=?',[(value,item['id']) for item in items])
            return {'updated':len(items)}
        if action=='remove_recent':
            item=self._item(db,p['id'])
            with db:db.execute('UPDATE items SET recent_hidden=1 WHERE id=?',(item['id'],))
            return True
        if action=='tags': return obtener_etiquetas_ordenadas_frecuencia(db,profile)
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
            with db:
                for item in items:
                    if field=='etiquetas':
                        names=set(normalizar(item['etiquetas'])); name=normalizar(value)[0]
                        if operation=='add': names.add(name)
                        else: names.discard(name)
                        updated=' '.join('+'+name for name in sorted(names))
                    else:
                        names=[name.strip() for name in item['autor'].splitlines() if name.strip()]
                        if operation=='add' and not any(name.casefold()==value.casefold() for name in names): names.append(value)
                        elif operation=='remove': names=[name for name in names if name.casefold()!=value.casefold()]
                        updated='\n'.join(names)
                    db.execute('UPDATE items SET '+field+'=? WHERE id=?',(updated,item['id']))
            return {'updated':len(items)}
        if action=='random':
            fn=obtener_semi_aleatorio_contextual if p.get('contextual') else obtener_aleatorio_puro
            return fn(db,perfil=profile)
        if action=='similar':
            self._item(db,p['id'])
            return obtener_similares(db,p['id'],profile)
        if action=='open':
            self._item(db,p['id']); result=manager.abrir_item(p['id'],p.get('mode','web'))
            with db:db.execute('UPDATE items SET recent_hidden=0 WHERE drive_id=?',(p['id'],))
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
            return assign_items(db,profile,ids,p.get('container_id'),p.get('name'))
        if action=='ungroup_container':
            self._item(db,p['id'])
            return ungroup_container(db,profile,p['id'])
        if action=='import_container':
            if not isinstance(p.get('path'),str): raise ValueError('Carpeta inválida')
            return import_container_folder(db,profile,p['path'])
        if action=='import_file':
            if not isinstance(p.get('path'),str):raise ValueError('Archivo inválido')
            return import_library_file(db,profile,p['path'],thumbnail_dir=self._dir/'portadas_auto')
        if action=='pick_import_folder':
            import tkinter as tk
            from tkinter import filedialog
            root=tk.Tk(); root.withdraw(); root.attributes('-topmost',True)
            try: return filedialog.askdirectory(parent=root,title='Selecciona la carpeta para importar') or None
            finally: root.destroy()
        if action=='delete_item':
            self._item(db,p['id'])
            return manager.eliminar_item(p['id'])
        if action=='preference':
            key,value=p['key'],str(p['value'])
            if key=='tema' and value not in ('auto','dark','light'): raise ValueError('Tema inválido')
            elif key=='modo' and value not in ('local','web'): raise ValueError('Modo inválido')
            elif key=='zoom' and not 100<=int(value)<=430: raise ValueError('Zoom inválido')
            elif key=='wallpaper_opacity' and not 0<=int(value)<=100: raise ValueError('Opacidad inválida')
            elif key=='wallpaper_blur' and not 0<=int(value)<=30: raise ValueError('Desenfoque inválido')
            elif key=='container_background_opacity' and not 0<=int(value)<=100: raise ValueError('Opacidad del fondo de contenedores inválida')
            elif key=='container_background_blur' and not 0<=int(value)<=30: raise ValueError('Desenfoque del fondo de contenedores inválido')
            elif key=='show_overlays' and value not in ('true','false'): raise ValueError('Preferencia inválida')
            elif key=='wallpaper': pass
            elif key not in ('tema','modo','zoom','wallpaper','wallpaper_opacity','wallpaper_blur','container_wallpaper','container_background_opacity','container_background_blur'): raise ValueError('Preferencia inválida')
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
            self._item(db,p['id'])
            if not ID_PATTERN.fullmatch(p['id']): raise ValueError('ID inválido')
            if len(p['data'])>12_000_000: raise ValueError('Imagen demasiado grande')
            from PIL import Image, ImageOps
            raw=base64.b64decode(p['data'],validate=True)
            with Image.open(BytesIO(raw)) as image:
                if image.format not in ('JPEG','PNG','WEBP'): raise ValueError('Usa JPG, PNG o WEBP')
                if image.width*image.height>30_000_000: raise ValueError('Imagen demasiado grande')
                image=ImageOps.exif_transpose(image).convert('RGB'); image.thumbnail((600,800), Image.Resampling.LANCZOS)
                covers=self._dir/'portadas'; covers.mkdir(exist_ok=True)
                temp=covers/(p['id']+'.tmp'); image.save(temp,'JPEG',quality=82,optimize=True,progressive=True)
                os.replace(temp,covers/(p['id']+'.jpg'))
            return True
        if action=='sync':
            with self._sync_lock:result=DriveSync(db).sincronizar_biblioteca(perfil=profile or None)
            DriveSync(db).exportar_libros(self._dir/'export_libros.json'); self._containers.clear(); return result
        if action=='profiles': return detectar_perfiles_drive()
        if action=='profile': cambiar_perfil_activo(p['id'],db); self._containers.clear(); return True
        if action=='backup':
            return crear_backup_en_biblioteca(library_root(db,profile),db,self._dir)
        if action=='backup_list':
            folder=library_root(db,profile)/'.balisco_backup'
            if not folder.is_dir(): return []
            return [{'name':file.name,'size':file.stat().st_size} for file in sorted(folder.glob('Balisco_Backup_*.zip'),reverse=True) if file.is_file() and not file.is_symlink()]
        if action=='backup_reveal':
            name=Path(str(p.get('name',''))).name
            if not name.startswith('Balisco_Backup_') or not name.endswith('.zip'): raise ValueError('Respaldo inválido')
            path=library_root(db,profile)/'.balisco_backup'/name
            if not path.is_file() or path.is_symlink(): raise FileNotFoundError('Respaldo ausente')
            import subprocess
            subprocess.Popen(['explorer.exe','/select,',str(path)])
            return True
        if action=='container':
            item=self._item(db,p['id'])
            if item['tipo']!='curso': raise ValueError('No es un contenedor')
            with db:db.execute('UPDATE items SET ultimo_acceso=CURRENT_TIMESTAMP WHERE id=?',(item['id'],))
            source=next((r['ruta_db'] for r in detectar_perfiles_drive() if r['id']==profile),None)
            if not source: raise FileNotFoundError('Perfil DriveFS no disponible')
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
            files=[record for record in records if not record.get('folder')]
            for folder in (record for record in records if record.get('folder')):
                prefix=folder['title'].casefold()+'/'
                folder['size']=sum(record['size'] for record in files if record['title'].casefold().startswith(prefix))
            # Materialize only entries confirmed by DriveFS. Their Drive IDs preserve personal metadata.
            with db:
                for record in records:
                    filename=PureWindowsPath(record['path']).name
                    folder=bool(record.get('folder'))
                    kind='curso' if folder else (classify_file(filename,allow_other=True) or 'archivo')
                    content='contenedor' if folder else 'documento' if kind=='pdf' else 'otro' if kind=='archivo' else kind
                    title=filename if folder else clean_book_title_and_author(filename,kind)[0] if kind=='pdf' else Path(filename).stem
                    db.execute('''INSERT INTO items(drive_id,titulo,autor,tipo,tipo_contenido,formato,categoria_macro,
                        ruta_relativa,ruta_portada,tamano_bytes,mime_type,perfil_drive,disponible,container_parent)
                        VALUES(?,?,?,?,?,?,'Containers',?,?,?,?,?,1,?) ON CONFLICT(drive_id) DO UPDATE SET
                        titulo=CASE WHEN items.titulo_personalizado=1 THEN items.titulo ELSE excluded.titulo END,
                        tipo=excluded.tipo,tipo_contenido=excluded.tipo_contenido,formato=excluded.formato,
                        categoria_macro='Containers',ruta_relativa=excluded.ruta_relativa,
                        tamano_bytes=excluded.tamano_bytes,mime_type=excluded.mime_type,
                        perfil_drive=excluded.perfil_drive,disponible=1,container_parent=excluded.container_parent''',
                        (record['id'],title,'',kind,content,'' if folder else Path(filename).suffix.lstrip('.').upper(),
                         record['path'],'portadas/'+record['id']+'.jpg',record['size'],record['mime'],profile,item['drive_id']))
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
            for record in records:
                meta=db.execute('''SELECT titulo,autor,etiquetas,rating,es_favorito,estado_lectura,
                    tipo_contenido,formato,fijado,search_override,ultimo_acceso FROM items
                    WHERE drive_id=? AND perfil_drive=?''',(record['id'],profile)).fetchone()
                if meta:record.update({key:meta[key] for key in meta.keys()})
            self._containers[p['id']]={r['id']:r for r in records}
            return [{k:v for k,v in r.items() if k!='path'} for r in records]
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
            allowed={'es_favorito','rating','estado_lectura'}
            if field not in allowed: raise ValueError('Propiedad del recurso no permitida')
            record=self._containers.get(p['container'],{}).get(ident)
            if not record:
                self._dispatch(db,'container',{'id':p['container']})
                record=self._containers.get(p['container'],{}).get(ident)
            if not record: raise ValueError('El recurso ya no está en este contenedor')
            if field=='es_favorito' and type(value) is not bool: raise ValueError('Favorito inválido')
            if field=='rating' and (type(value) is not int or value not in range(6)): raise ValueError('Calificación inválida')
            if field=='estado_lectura' and value not in ('pendiente','interesado','leyendo','leido','abandonado'):
                raise ValueError('Estado de lectura inválido')
            with db:
                updated=db.execute('UPDATE items SET '+field+'=? WHERE drive_id=? AND perfil_drive=?',
                                   (int(value) if field=='es_favorito' else value,ident,profile)).rowcount
            if not updated: raise ValueError('Este archivo todavía no tiene propiedades de biblioteca')
            return {'field':field,'value':int(value) if field=='es_favorito' else value}
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
            storage=library/'Storage';storage.mkdir(exist_ok=True)
            target=inside(storage/filename,library)
            if target.exists(): raise FileExistsError('Ya existe un archivo con ese nombre en Storage')
            shutil.move(str(source),str(target))
            ext=target.suffix.casefold()
            tipo=classify_file(filename,allow_other=True)
            tipo_contenido='documento' if tipo=='pdf' else 'otro' if tipo=='archivo' else tipo
            relative=str(PureWindowsPath(library.parent.name,'Biblioteca','Storage',filename))
            try:
                with db:
                    item=db.execute('SELECT id FROM items WHERE drive_id=? AND perfil_drive=?',(p['id'],profile)).fetchone()
                    if item:
                        db.execute('''UPDATE items SET tipo=?,tipo_contenido=?,formato=?,categoria_macro='Storage',
                            subcategoria='',ruta_relativa=?,tamano_bytes=?,mime_type=?,disponible=1,container_parent='' WHERE id=?''',
                            (tipo,tipo_contenido,ext.lstrip('.').upper(),relative,target.stat().st_size,record.get('mime'),item['id']))
                    else:
                        title,author=clean_book_title_and_author(filename,tipo) if tipo=='pdf' else (target.stem,'')
                        db.execute('''INSERT INTO items(drive_id,titulo,autor,tipo,tipo_contenido,formato,categoria_macro,
                            ruta_relativa,ruta_portada,tamano_bytes,mime_type,perfil_drive,disponible)
                            VALUES(?,?,?,?,?,?,'Storage',?,?,?, ?,?,1)''',
                            (p['id'],title,author,tipo,tipo_contenido,ext.lstrip('.').upper(),relative,
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
            storage=library/'Storage';storage.mkdir(exist_ok=True)
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
                        relative=str(PureWindowsPath(library.parent.name,'Biblioteca','Storage',parts[-1],*relative_parts))
                        item=db.execute('SELECT id FROM items WHERE drive_id=? AND perfil_drive=?',(record['id'],profile)).fetchone()
                        if item:
                            db.execute('''UPDATE items SET tipo=?,tipo_contenido=?,formato=?,categoria_macro='Storage',
                                subcategoria='',ruta_relativa=?,tamano_bytes=?,mime_type=?,disponible=1,container_parent='' WHERE id=?''',
                                (tipo,tipo_contenido,ext.lstrip('.').upper(),relative,destination.stat().st_size,record.get('mime'),item['id']))
                        else:
                            title,author=clean_book_title_and_author(destination.name,tipo) if tipo=='pdf' else (destination.stem,'')
                            db.execute('''INSERT INTO items(drive_id,titulo,autor,tipo,tipo_contenido,formato,categoria_macro,
                                ruta_relativa,ruta_portada,tamano_bytes,mime_type,perfil_drive,disponible)
                                VALUES(?,?,?,?,?,?,'Storage',?,?,?, ?,?,1)''',
                                (record['id'],title,author,tipo,tipo_contenido,ext.lstrip('.').upper(),relative,
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
            from send2trash import send2trash as send2trash_fn
            send2trash_fn(str(target))
            with db:
                entry_rows=db.execute('SELECT drive_id,ruta_relativa FROM container_entries WHERE container_drive_id=? AND perfil_drive=?',
                                      (p['container'],profile)).fetchall()
                container_parts=PureWindowsPath(container['ruta_relativa']).parts
                folder_parts=tuple(container_parts)+tuple(parts)
                for row in entry_rows:
                    path_parts=PureWindowsPath(row['ruta_relativa']).parts
                    if len(path_parts)>len(folder_parts) and all(a.casefold()==b.casefold() for a,b in zip(path_parts,folder_parts)):
                        ids.add(row['drive_id'])
                for ident in ids:
                    db.execute('DELETE FROM container_entries WHERE drive_id=? AND container_drive_id=?',(ident,p['container']))
                    db.execute('UPDATE items SET disponible=0 WHERE drive_id=? AND perfil_drive=?',(ident,profile))
                    db.execute('''INSERT INTO pending_container_moves(drive_id,expected_relative,container_drive_id,perfil_drive)
                        VALUES(?,'','__removed__',?) ON CONFLICT(drive_id) DO UPDATE SET expected_relative='',
                        container_drive_id='__removed__',perfil_drive=excluded.perfil_drive,created_at=CURRENT_TIMESTAMP''',(ident,profile))
            for ident in ids: self._containers.get(p['container'],{}).pop(ident,None)
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
                opened=webbrowser.open('https://drive.google.com/file/d/'+record['id']+'/view')
                with db:db.execute('UPDATE items SET ultimo_acceso=CURRENT_TIMESTAMP,recent_hidden=0 WHERE drive_id=?',(p['id'],))
                return opened
            item=dict(container,ruta_relativa=record['path']); path=manager.ruta_local(item)
            if action=='container_open':
                os.startfile(str(path))
                with db:db.execute('UPDATE items SET ultimo_acceso=CURRENT_TIMESTAMP,recent_hidden=0 WHERE drive_id=?',(p['id'],))
            else:
                from send2trash import send2trash
                send2trash(str(path)); del self._containers[p['container']][p['id']]
                with db:
                    db.execute('DELETE FROM container_entries WHERE drive_id=? AND container_drive_id=?',(p['id'],p['container']))
                    db.execute('UPDATE items SET disponible=0 WHERE drive_id=? AND perfil_drive=?',(p['id'],profile))
                    db.execute('''INSERT INTO pending_container_moves(drive_id,expected_relative,container_drive_id,perfil_drive)
                        VALUES(?,'','__removed__',?) ON CONFLICT(drive_id) DO UPDATE SET expected_relative='',
                        container_drive_id='__removed__',perfil_drive=excluded.perfil_drive,created_at=CURRENT_TIMESTAMP''',(p['id'],profile))
            return True
        if action=='companion_get':
            from .companion import CompanionEngine
            return CompanionEngine().get_state()
        if action=='companion_interact':
            from .companion import CompanionEngine
            engine = CompanionEngine()
            tipo = p.get('tipo', 'charla')
            res = engine.update_interaction(tipo)
            if p.get('mensaje'):
                engine.registrar_mensaje('usuario', p['mensaje'])
                if p.get('respuesta'):
                    engine.registrar_mensaje('companion', p['respuesta'], res.get('sprite'), res.get('humor'))
            return res
        if action=='companion_descansar':
            from .companion import CompanionEngine
            CompanionEngine().descansar()
            return CompanionEngine().get_state()
        raise ValueError('Acción no soportada')
