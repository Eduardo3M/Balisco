"""Thread-safe, narrow desktop bridge. All content access is explicit."""
import base64
from contextlib import closing
from io import BytesIO
import json
import os
from pathlib import Path, PureWindowsPath
import sqlite3
import threading
import time
import webbrowser
from .database import DATA_DIR, conectar, configurar, preferencia
from .items_manager import ItemsManager
from .tags_manager import TagsManager, obtener_etiquetas_ordenadas_frecuencia
from .search_parser import agregar_filtro, limpiar_todos_filtros, construir_query_sql
from .serendipity import obtener_aleatorio_puro, obtener_semi_aleatorio_contextual
from .drive_sync import (DriveSync, Metadata, conectar_db_drive_ro, detectar_perfiles_drive,
                         extraer_ids_proto, ID_PATTERN, obtener_letra_drive, cambiar_perfil_activo)
from .backup_manager import crear_backup_en_drive

class DesktopAPI:
    def __init__(self, data_dir=None, started=None):
        self._dir=Path(data_dir or DATA_DIR)
        self._dbpath=self._dir/'biblioteca.db'
        self._lock=threading.RLock()
        self._courses={}
        self._started=started or time.perf_counter()
        from .migrations import migrate_author
        migrate_author(self._dbpath)
        from .migrations import migrate_interested
        migrate_interested(self._dbpath)
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
            if action in self.WINDOW_ACTIONS:
                return {'ok':True,'data':self._window_action(action,payload or {})}
            with self._lock, closing(self._connect()) as db:
                value=self._dispatch(db,action,payload or {})
            return {'ok':True,'data':value}
        except Exception as exc:
            return {'ok':False,'error':str(exc),'kind':type(exc).__name__}
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
    def _dispatch(self,db,action,p):
        profile=preferencia(db,'id_perfil_drive','')
        manager=ItemsManager(db)
        if action=='bootstrap':
            return {'prefs':{r['clave']:r['valor'] for r in db.execute("SELECT * FROM configuracion WHERE clave IN ('tema','zoom','modo','id_perfil_drive','wallpaper','wallpaper_opacity','wallpaper_blur','show_overlays')")},'count':db.execute('SELECT count(*) FROM items WHERE disponible=1 AND perfil_drive=?',(profile,)).fetchone()[0]}
        if action=='ready':
            metrics={'ready_ms':round((time.perf_counter()-self._started)*1000,1),'renderer':'edgechromium','frontend':p}
            (self._dir/'performance.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
            return metrics
        if action=='query':
            filters=limpiar_todos_filtros()
            for token in p.get('tokens',[]): filters=agregar_filtro(str(token),filters)
            sql,args=construir_query_sql(filters,profile)
            sql=sql.replace('SELECT i.*','SELECT i.drive_id,i.titulo,i.autor,i.tipo,i.estado_lectura,i.es_favorito,i.rating,i.tamano_bytes,i.categoria_macro')
            return {'items':[dict(r) for r in db.execute(sql,args)],'filters':filters['pildoras']}
        if action=='detail':
            item=self._item(db,p['id']); item['url']=manager.url(p['id']); return item
        if action=='update':
            self._item(db,p['id'])
            methods={'titulo':manager.cambiar_titulo,'autor':manager.cambiar_autor,'notas':manager.actualizar_notas,'rating':manager.cambiar_rating,'estado_lectura':manager.cambiar_estado_lectura,'es_favorito':manager.cambiar_favorito,'etiquetas':TagsManager(db).actualizar_etiquetas_item}
            if p['field'] not in methods: raise ValueError('Campo no editable')
            methods[p['field']](p['id'],p['value']); return self._item(db,p['id'])
        if action=='tags': return obtener_etiquetas_ordenadas_frecuencia(db,profile)
        if action=='authors':
            from collections import Counter
            counts=Counter(name.strip() for row in db.execute("SELECT autor FROM items WHERE disponible=1 AND perfil_drive=?",(profile,)) for name in row[0].splitlines() if name.strip())
            return [dict(author=name,total=count) for name,count in sorted(counts.items(),key=lambda x:(-x[1],x[0].casefold()))]
        if action=='bulk_metadata':
            from .tags_manager import normalizar
            ids=p.get('ids',[]); field=p.get('field'); operation=p.get('operation'); value=str(p.get('value','')).strip()
            if not isinstance(ids,list) or not ids or len(ids)>10000 or len(set(ids))!=len(ids): raise ValueError('Selección inválida')
            if field not in ('autor','etiquetas') or operation not in ('add','remove') or not value: raise ValueError('Cambio masivo inválido')
            if field=='etiquetas' and len(normalizar(value))!=1: raise ValueError('Una etiqueta por cambio')
            if field=='autor' and ('\n' in value or '\r' in value): raise ValueError('Un autor por cambio')
            items=[self._item(db,ident) for ident in ids]
            if any(item['tipo']!='pdf' for item in items): raise ValueError('Selecciona solo libros')
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
        if action=='open':
            self._item(db,p['id']); return manager.abrir_item(p['id'],p.get('mode','web'))
        if action=='reveal':
            self._item(db,p['id']); return manager.mostrar_en_explorador(p['id'])
        if action=='preference':
            key,value=p['key'],str(p['value'])
            if key=='tema' and value not in ('auto','dark','light'): raise ValueError('Tema inválido')
            elif key=='modo' and value not in ('local','web'): raise ValueError('Modo inválido')
            elif key=='zoom' and not 100<=int(value)<=430: raise ValueError('Zoom inválido')
            elif key=='wallpaper_opacity' and not 0<=int(value)<=100: raise ValueError('Opacidad inválida')
            elif key=='wallpaper_blur' and not 0<=int(value)<=30: raise ValueError('Desenfoque inválido')
            elif key=='show_overlays' and value not in ('true','false'): raise ValueError('Preferencia inválida')
            elif key=='wallpaper': pass
            elif key not in ('tema','modo','zoom','wallpaper','wallpaper_opacity','wallpaper_blur','show_overlays'): raise ValueError('Preferencia inválida')
            with db: configurar(db,key,value)
            return True
        if action=='wallpapers_list':
            dirs=[Path(__file__).parent.parent/'wallpapers', self._dir/'wallpapers']
            found=[]; seen=set()
            for d in dirs:
                if d.is_dir():
                    for f in sorted(d.iterdir()):
                        if f.is_file() and f.suffix.lower() in ('.jpg','.jpeg','.png','.webp') and f.name not in seen:
                            seen.add(f.name)
                            found.append({'name':f.stem.replace('_',' '),'filename':f.name,'size':f.stat().st_size})
            return found
        if action=='get_wallpaper':
            fn=p.get('filename')
            if not fn: return None
            fn=Path(fn).name
            dirs=[Path(__file__).parent.parent/'wallpapers', self._dir/'wallpapers']
            for d in dirs:
                f=d/fn
                if f.is_file() and not f.is_symlink():
                    mime='image/png' if f.suffix.lower()=='.png' else ('image/webp' if f.suffix.lower()=='.webp' else 'image/jpeg')
                    return f'data:{mime};base64,'+base64.b64encode(f.read_bytes()).decode('ascii')
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
                with db: configurar(db,'wallpaper',clean)
                return {'filename':clean,'name':target.stem}
        if action=='cover':
            self._item(db,p['id']); path=self._dir/'portadas'/(p['id']+'.jpg')
            if not ID_PATTERN.fullmatch(p['id']): raise ValueError('ID inválido')
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
            result=DriveSync(db).sincronizar_biblioteca(perfil=profile or None)
            DriveSync(db).exportar_libros(self._dir/'export_libros.json'); self._courses.clear(); return result
        if action=='profiles': return detectar_perfiles_drive()
        if action=='profile': cambiar_perfil_activo(p['id'],db); self._courses.clear(); return True
        if action=='backup':
            root=preferencia(db,'unidad_drive:'+profile) or obtener_letra_drive()
            name='Mi unidad' if (Path(root)/'Mi unidad'/'Biblioteca').is_dir() else 'My Drive'
            return crear_backup_en_drive(root,db,self._dir,name)
        if action=='course':
            item=self._item(db,p['id'])
            if item['tipo']!='curso': raise ValueError('No es un curso')
            source=next((r['ruta_db'] for r in detectar_perfiles_drive() if r['id']==profile),None)
            if not source: raise FileNotFoundError('Perfil DriveFS no disponible')
            with closing(conectar_db_drive_ro(source)) as conn:
                conn.execute('BEGIN'); meta=Metadata(conn)
            root=None
            for ident,node in meta.nodes.items():
                try:
                    if extraer_ids_proto(node['proto'])[0]==p['id']: root=ident; break
                except (ValueError,UnicodeError): continue
            if root is None: raise FileNotFoundError('Curso ausente de DriveFS')
            rootparts=meta.parts(root); records=[]; stack=list(meta.children.get(root,[])); seen=set()
            while stack:
                ident=stack.pop()
                if ident in seen: continue
                seen.add(ident); node=meta.nodes.get(ident); parts=meta.parts(ident)
                if not node or not parts or not rootparts or parts[:len(rootparts)]!=rootparts: continue
                if node['is_folder']: stack.extend(meta.children.get(ident,[])); continue
                try: drive_id,_=extraer_ids_proto(node['proto'])
                except (ValueError,UnicodeError): continue
                records.append({'id':drive_id,'title':' / '.join(parts[len(rootparts):]),'size':node['file_size'] or 0,'path':str(PureWindowsPath(*parts)),'mime':node['mime_type']})
            records.sort(key=lambda r:r['title'].casefold())
            self._courses[p['id']]={r['id']:r for r in records}
            return [{k:v for k,v in r.items() if k!='path'} for r in records]
        if action in ('course_open','course_trash'):
            course=self._item(db,p['course'])
            self._dispatch(db,'course',{'id':p['course']})
            record=self._courses.get(p['course'],{}).get(p['id'])
            if not record: raise ValueError('Vuelve a cargar el curso')
            if action=='course_open' and p.get('mode')=='web':
                return webbrowser.open('https://drive.google.com/file/d/'+record['id']+'/view')
            item=dict(course,ruta_relativa=record['path']); path=manager.ruta_local(item)
            if action=='course_open': os.startfile(str(path))
            else:
                from send2trash import send2trash
                send2trash(str(path)); del self._courses[p['course']][p['id']]
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
