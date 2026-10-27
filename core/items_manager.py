import os
import subprocess
from pathlib import Path, PureWindowsPath
import webbrowser
from .database import STATES, preferencia
from .drive_sync import DriveSync, obtener_letra_drive, ID_PATTERN

class ItemsManager:
    def __init__(self,db): self.db=db
    def obtener(self,drive_id):
        row=self.db.execute('SELECT * FROM items WHERE drive_id=?',(drive_id,)).fetchone()
        if not row: raise KeyError('Elemento desconocido')
        return dict(row)
    def ruta_local(self,item):
        from .library_layout import root_id, mounted_drive
        root=mounted_drive(self.db,item['perfil_drive']) if root_id(self.db,item['perfil_drive']) else preferencia(self.db,'unidad_drive:'+item['perfil_drive']) or obtener_letra_drive()
        rel=PureWindowsPath(item['ruta_relativa'])
        if rel.is_absolute() or rel.drive or '..' in rel.parts or any(p.startswith('.') for p in rel.parts): raise ValueError('Ruta no permitida')
        return Path(root).joinpath(*rel.parts)
    def url(self,drive_id):
        item=self.obtener(drive_id)
        if not ID_PATTERN.fullmatch(drive_id): raise ValueError('ID inválido')
        return ('https://drive.google.com/drive/folders/'+drive_id if item['tipo']=='curso' else 'https://drive.google.com/file/d/'+drive_id+'/view')
    def auto_reparar_ruta(self,drive_id):
        item=self.obtener(drive_id)
        DriveSync(self.db).sincronizar_biblioteca(perfil=item['perfil_drive'])
        item=self.obtener(drive_id)
        if not item['disponible']: raise FileNotFoundError('Elemento no disponible en Drive')
        return str(self.ruta_local(item))
    def abrir_item(self,drive_id,modo='local'):
        if modo not in ('local','web','balisco'): raise ValueError('Modo desconocido')
        item=self.obtener(drive_id)
        if modo=='web':
            if not webbrowser.open(self.url(drive_id)): return False
        else:
            path=self.ruta_local(item)
            if not path.exists(): path=Path(self.auto_reparar_ruta(drive_id))
            if not path.exists(): raise FileNotFoundError(str(path))
            os.startfile(str(path))
        with self.db: self.db.execute('UPDATE items SET ultimo_acceso=CURRENT_TIMESTAMP WHERE drive_id=?',(drive_id,))
        return True
    def mostrar_en_explorador(self,drive_id):
        item=self.obtener(drive_id)
        path=self.ruta_local(item)
        if not path.exists(): path=Path(self.auto_reparar_ruta(drive_id))
        if not path.exists(): raise FileNotFoundError(str(path))
        if item['tipo']=='curso': os.startfile(str(path))
        else: subprocess.Popen(['explorer.exe','/select,',str(path)])
        return True
    def _update(self,drive_id,field,value):
        allowed={'notas','rating','estado_lectura','titulo','autor','es_favorito','idioma'}
        if field not in allowed: raise ValueError('Campo no permitido')
        with self.db: return self.db.execute('UPDATE items SET '+field+'=? WHERE drive_id=?',(value,drive_id)).rowcount>0
    def actualizar_notas(self,drive_id,texto_notas):
        return self._update(drive_id,'notas',str(texto_notas))
    def cambiar_estado_lectura(self,drive_id,nuevo_estado):
        if nuevo_estado not in STATES: raise ValueError('Estado inválido')
        return self._update(drive_id,'estado_lectura',nuevo_estado)
    def cambiar_rating(self,drive_id,nuevo_rating):
        if type(nuevo_rating) is not int or nuevo_rating not in range(6): raise ValueError('Rating debe ser entero de 0 a 5')
        return self._update(drive_id,'rating',nuevo_rating)
    def cambiar_titulo(self,drive_id,titulo):
        if not titulo.strip(): raise ValueError('Título vacío')
        with self.db: return self.db.execute('UPDATE items SET titulo=?,titulo_personalizado=1 WHERE drive_id=?',(titulo.strip(),drive_id)).rowcount>0
    def cambiar_autor(self,drive_id,autor):
        names=[];seen=set()
        for name in str(autor).splitlines():
            name=' '.join(name.split())
            if name and name.casefold() not in seen:
                names.append(name);seen.add(name.casefold())
        return self._update(drive_id,'autor','\n'.join(names))
    def cambiar_favorito(self,drive_id,favorito):
        if type(favorito) not in (bool,int) or favorito not in (0,1): raise ValueError('Favorito inválido')
        return self._update(drive_id,'es_favorito',int(favorito))
    def cambiar_idioma(self,drive_id,idioma):
        return self._update(drive_id,'idioma',str(idioma or '').strip())
    def eliminar_item(self,drive_id):
        from send2trash import send2trash
        item=self.obtener(drive_id); path=self.ruta_local(item)
        if not path.exists(): path=Path(self.auto_reparar_ruta(drive_id))
        send2trash(str(path))
        with self.db:
            self.db.execute('DELETE FROM container_entries WHERE container_drive_id=?',(drive_id,))
            if item['tipo']=='pdf':
                self.db.execute('DELETE FROM container_entries WHERE drive_id=?',(drive_id,))
                self.db.execute('UPDATE items SET disponible=0 WHERE drive_id=?',(drive_id,))
                self.db.execute('''INSERT INTO pending_container_moves(drive_id,expected_relative,container_drive_id,perfil_drive)
                    VALUES(?,?,'__removed__',?) ON CONFLICT(drive_id) DO UPDATE SET
                    expected_relative=excluded.expected_relative,container_drive_id='__removed__',
                    perfil_drive=excluded.perfil_drive,created_at=CURRENT_TIMESTAMP''',
                    (drive_id,item['ruta_relativa'],item['perfil_drive']))
            else:
                self.db.execute('DELETE FROM items WHERE drive_id=?',(drive_id,))
        return True
