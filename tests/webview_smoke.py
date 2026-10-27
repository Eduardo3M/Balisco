"""Exercise the current search and editing UI with an isolated WebView2 database."""
from contextlib import closing
from pathlib import Path
import json
import sys
import tempfile
import threading
import time

import webview

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.database import conectar, configurar
from core.desktop_api import DesktopAPI

RESULT = {}
JS = r"""(async()=>{
 const $=id=>document.getElementById(id),S=window.balisco.state;
 const wait=async(test,label)=>{for(let i=0;i<150;i++){if(test())return;await new Promise(resolve=>setTimeout(resolve,30));}throw Error('Timeout: '+label);};
 await wait(()=>S.items.length===2&&document.querySelectorAll('.card').length===2,'cards');
 document.querySelector('.card').click();await wait(()=>S.selected?.drive_id,'selection');
 const id=S.selected.drive_id;
 $('notes').value='Nota de prueba';$('notes').dispatchEvent(new Event('input'));
 await window.balisco.flush();
 const detail=await pywebview.api.call('detail',{id});
 if(detail?.data?.notas!=='Nota de prueba')throw Error('Notes were not saved: '+JSON.stringify(detail));
 $('addAuthor').click();$('authorInput').value='Ana Torres';$('authorForm').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));
 await wait(()=>S.selected?.autor.includes('Ana Torres'),'author');
 $('addTag').click();$('tagInput').value='prueba';$('tagForm').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));
 await wait(()=>S.selected?.etiquetas.includes('+prueba'),'tag');
 $('searchToggle').click();await wait(()=>$('tagSuggestions').querySelector('[data-suggestion]'),'empty search suggestions');
 if($('ghost').value||!$('tagSuggestions').textContent.includes('ETIQUETAS RECIENTES'))throw Error('Empty search suggestions missing');
 $('ghost').value='+prueba';$('ghost').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));
 await wait(()=>S.tokens.includes('+prueba')&&S.items.length===1,'tag search');
 document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
 await wait(()=>S.tokens.length===0&&S.items.length===2,'clear search');
 $('metadata').click();await wait(()=>S.view==='metadata'&&$('metadataItems').textContent.includes('prueba'),'metadata');
 $('metadata').click();await wait(()=>S.view==='grid','grid return');
 return {ok:true,checks:['selection','notes','author','tag','empty suggestions','tag search','metadata']};
})().catch(error=>({ok:false,error:error.message,stack:error.stack}))"""


def run(window):
    try:
        deadline = time.monotonic() + 20
        while not window.evaluate_js('Boolean(window.balisco?.state.items.length===2)'):
            if time.monotonic() > deadline:
                raise AssertionError('Bootstrap timeout')
            time.sleep(.05)
        done = threading.Event()
        window.evaluate_js(JS, callback=lambda value: (RESULT.update(value), done.set()))
        if not done.wait(12):
            RESULT.update(ok=False, error='UI timeout')
    except Exception as error:
        RESULT.update(ok=False, error=str(error))
    finally:
        window.destroy()


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='balisco-webview-') as temp:
        with closing(conectar(Path(temp) / 'biblioteca.db')) as db, db:
            configurar(db, 'id_perfil_drive', 'fixture')
            db.executemany(
                'INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive) VALUES(?,?,?,?,?)',
                [('fixture_book_01', 'Libro uno', 'pdf', 'uno.pdf', 'fixture'),
                 ('fixture_book_02', 'Libro dos', 'pdf', 'dos.pdf', 'fixture')],
            )
        api = DesktopAPI(temp)
        window = webview.create_window('Balisco UI test', str(ROOT / 'ui' / 'index.html'),
                                       js_api=api, width=1100, height=750)
        webview.start(run, window, gui='edgechromium', private_mode=True)
        print(json.dumps(RESULT, ensure_ascii=False))
        if not RESULT.get('ok'):
            sys.exit(1)
