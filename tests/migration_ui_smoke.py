"""Check the migration explanation, review step, and final action in WebView2."""
from contextlib import closing
from pathlib import Path
import json
import sys
import tempfile
import time
import webview

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from core.database import conectar, configurar
from tests.ui_smoke_fixture import DesktopAPI


class MigrationAPI(DesktopAPI):
    def __init__(self,data_dir):
        super().__init__(data_dir)
        self.migrated=False

    def _dispatch(self,db,action,payload):
        if action=='drive_status':return {'state':'ready' if self.migrated else 'needs_migration','profile':'fixture'}
        if action=='migration_preview':return {'root':r'G:\Mi unidad\Biblioteca','count':2,'moves':[
            {'from':r'G:\Mi unidad\Biblioteca\Storage\Libro.pdf','to':r'G:\Mi unidad\Biblioteca\historia\Libro.pdf'},
            {'from':r'G:\Mi unidad\Biblioteca\Containers\Curso','to':r'G:\Mi unidad\Biblioteca\_Inbox\Curso'}]}
        if action=='migration_run':
            self.migrated=True
            return {'moved':2,'backup':r'G:\Mi unidad\Biblioteca\.balisco\backups\copia.zip'}
        return super()._dispatch(db,action,payload)


result={}
def run(window):
    try:
        deadline=time.monotonic()+10
        while not window.evaluate_js("document.getElementById('setupTitle').textContent==='Vamos a organizar tus archivos'"):
            if time.monotonic()>deadline:raise AssertionError('No apareció la explicación de migración')
            time.sleep(.05)
        description=window.evaluate_js("document.getElementById('setupDetails').textContent")
        if 'primera etiqueta' not in description or 'copia de tus datos' not in description:
            raise AssertionError('Faltan instrucciones concretas')
        window.evaluate_js("document.querySelector('#setupActions button').click()")
        deadline=time.monotonic()+5
        while not window.evaluate_js("!document.getElementById('setupMoveList').hidden"):
            if time.monotonic()>deadline:raise AssertionError('No se abrió la revisión')
            time.sleep(.05)
        paths=window.evaluate_js("document.getElementById('setupMoveList').textContent")
        if 'Storage\\Libro.pdf' not in paths or '_Inbox\\Curso' not in paths:
            raise AssertionError('No se muestran los movimientos previstos')
        button=window.evaluate_js("document.querySelector('#setupActions button').textContent")
        if button!='Crear respaldo y organizar ahora':raise AssertionError(button)
        window.evaluate_js("document.querySelector('#setupActions button').click()")
        deadline=time.monotonic()+10
        while not window.evaluate_js("document.getElementById('setupView').hidden"):
            if time.monotonic()>deadline:raise AssertionError('La biblioteca no se abrió tras organizar')
            time.sleep(.05)
        result.update(ok=True,movements=2)
    except Exception as error:result.update(ok=False,error=str(error))
    finally:window.destroy()


if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='balisco-migration-ui-') as directory:
        with closing(conectar(Path(directory)/'biblioteca.db')) as db,db:
            configurar(db,'id_perfil_drive','fixture')
        api=MigrationAPI(directory)
        window=webview.create_window('Balisco migration test',str(ROOT/'ui'/'index.html'),js_api=api,width=1100,height=750)
        webview.start(run,window,gui='edgechromium',private_mode=True)
        print(json.dumps(result,ensure_ascii=False))
        if not result.get('ok'):sys.exit(1)
