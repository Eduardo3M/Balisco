"""Switch back from a profile awaiting a library location in WebView2."""
from contextlib import closing
from pathlib import Path
import json
import sys
import tempfile
import time
import webview

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from core.database import conectar, configurar, preferencia
from tests.ui_smoke_fixture import DesktopAPI


class AccountsAPI(DesktopAPI):
    def _dispatch(self,db,action,payload):
        if action=='profiles':return [{'id':'account_A'},{'id':'account_B'}]
        if action=='profile':
            with db:configurar(db,'id_perfil_drive',payload['id'])
            return True
        if action=='drive_status':
            current=preferencia(db,'id_perfil_drive')
            return {'state':'ready' if current=='account_A' else 'needs_location','profile':current}
        return super()._dispatch(db,action,payload)


result={}
def until(window,expression,message,seconds=10):
    deadline=time.monotonic()+seconds
    while not window.evaluate_js(expression):
        if time.monotonic()>deadline:raise AssertionError(message)
        time.sleep(.05)


def run(window):
    try:
        until(window,"document.getElementById('setupView').hidden && window.balisco?.state.items.length===1",'No abrió la cuenta inicial')
        window.evaluate_js("document.getElementById('driveTools').click()")
        until(window,"Boolean(document.querySelector('#popover [data-profile=account_B]'))",'No apareció la otra cuenta')
        window.evaluate_js("document.querySelector('#popover [data-profile=account_B]').click()")
        until(window,"!document.getElementById('setupView').hidden && document.getElementById('setupTitle').textContent==='Ubica tu biblioteca'",'No apareció la configuración de la segunda cuenta')
        window.evaluate_js("document.querySelector('#setupAccount .setup-switch-account').click()")
        until(window,"Boolean(document.querySelector('#setupAccount .setup-profile-choice'))",'No apareció el selector dentro del asistente')
        window.evaluate_js("[...document.querySelectorAll('#setupAccount .setup-profile-choice')].find(button=>button.textContent.startsWith('account_A')).click()")
        until(window,"document.getElementById('setupView').hidden && window.balisco?.state.items.length===1",'No volvió a la cuenta anterior')
        result.update(ok=True,returned_to='account_A')
    except Exception as error:result.update(ok=False,error=str(error))
    finally:window.destroy()


if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='balisco-account-switch-ui-') as directory:
        with closing(conectar(Path(directory)/'biblioteca.db')) as db,db:
            configurar(db,'id_perfil_drive','account_A')
            db.execute("INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive) VALUES('account_A_book','Libro','pdf','Libro.pdf','account_A')")
        api=AccountsAPI(directory)
        window=webview.create_window('Balisco account switch test',str(ROOT/'ui'/'index.html'),js_api=api,width=1100,height=750)
        webview.start(run,window,gui='edgechromium',private_mode=True)
        print(json.dumps(result,ensure_ascii=False))
        if not result.get('ok'):sys.exit(1)
