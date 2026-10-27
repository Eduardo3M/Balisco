"""Exercise the first-run location screen in an isolated WebView2 window."""
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


class SetupAPI(DesktopAPI):
    def __init__(self,data_dir):
        super().__init__(data_dir)
        self.chosen=False
    def _dispatch(self,db,action,payload):
        if action=='drive_status':return {'state':'ready' if self.chosen else 'needs_location','profile':'fixture'}
        if action=='library_pick':
            self.chosen=True
            return {'state':'ready','profile':'fixture'}
        return super()._dispatch(db,action,payload)


result={}
def run(window):
    try:
        deadline=time.monotonic()+10
        while not window.evaluate_js("Boolean(document.getElementById('setupView')&&!document.getElementById('setupView').hidden)"):
            if time.monotonic()>deadline:raise AssertionError('No se mostró el paso de ubicación')
            time.sleep(.05)
        title=window.evaluate_js("document.getElementById('setupTitle').textContent")
        if title!='Ubica tu biblioteca':raise AssertionError(title)
        window.evaluate_js("document.querySelector('#setupActions button').click()")
        deadline=time.monotonic()+10
        while not window.evaluate_js("document.getElementById('setupView').hidden && window.balisco?.state.items.length===1"):
            if time.monotonic()>deadline:
                debug=window.evaluate_js("({hidden:document.getElementById('setupView').hidden,items:window.balisco?.state.items.length,status:document.getElementById('status').textContent,summary:document.getElementById('summary').textContent,toast:document.getElementById('toast').textContent})")
                raise AssertionError('La biblioteca no se abrió al seleccionarla: '+str(debug))
            time.sleep(.05)
        result.update(ok=True,setup=title,items=1)
    except Exception as error:result.update(ok=False,error=str(error))
    finally:window.destroy()


if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='balisco-setup-ui-') as directory:
        with closing(conectar(Path(directory)/'biblioteca.db')) as db,db:
            configurar(db,'id_perfil_drive','fixture')
            db.execute("INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive) VALUES('fixture_book_01','Libro','pdf','Libro.pdf','fixture')")
        api=SetupAPI(directory)
        window=webview.create_window('Balisco setup test',str(ROOT/'ui'/'index.html'),js_api=api,width=1100,height=750)
        webview.start(run,window,gui='edgechromium',private_mode=True)
        print(json.dumps(result,ensure_ascii=False))
        if not result.get('ok'):sys.exit(1)
