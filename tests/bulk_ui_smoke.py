"""Exercise author browsing and bulk edits in a real, isolated WebView2 window."""
from contextlib import closing
from pathlib import Path
import json
import sys
import tempfile
import threading
import time
import webview
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.database import conectar, configurar
from core.desktop_api import DesktopAPI

root=Path(__file__).resolve().parents[1]
result={}
def run(window):
    try:
        deadline=time.monotonic()+12
        while not window.evaluate_js('Boolean(window.balisco?.state.items.length===2)'):
            if time.monotonic()>deadline:
                state=window.evaluate_js("({url:location.href,ready:!!window.balisco,items:window.balisco?.state.items.length,status:document.getElementById('status')?.textContent,toast:document.getElementById('toast')?.textContent})")
                raise AssertionError(f'Bootstrap timeout: {state}')
            time.sleep(.05)
        done=threading.Event()
        script=r"""(async()=>{
          const S=window.balisco.state,$=id=>document.getElementById(id);
          const wait=async f=>{const end=performance.now()+5000;while(!f()){if(performance.now()>end)throw Error('Timeout');await new Promise(r=>setTimeout(r,25));}};
          $('metadata').click();await wait(()=>S.view==='metadata');
          $('metadataView').querySelector('[data-meta-tab="author"]').click();await wait(()=>$('metadataItems').textContent.includes('Ana Torres'));
          $('metadataItems').querySelector('[data-meta-open="Ana Torres"]').click();await wait(()=>S.view==='grid'&&S.items.length===1);
          document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await wait(()=>S.items.length===2);
          await wait(()=>document.querySelectorAll('.card').length===2);
          const cards=[...document.querySelectorAll('.card')];cards[0].click();await wait(()=>S.bulkIds.size===1);
          cards[1].dispatchEvent(new MouseEvent('click',{bubbles:true,ctrlKey:true}));await wait(()=>S.bulkIds.size===2&&S.selected);
          $('addAuthor').click();$('authorInput').value='María Sol';$('authorForm').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));
          await wait(()=>S.selected.autor.includes('María Sol'));
          $('addTag').click();$('tagInput').value='arte';$('tagForm').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));
          await wait(()=>S.selected.etiquetas.includes('+arte'));
          const ids=[...S.bulkIds],details=await Promise.all(ids.map(async id=>(await pywebview.api.call('detail',{id})).data));
          if(!details.every(item=>item.autor.includes('María Sol')&&item.etiquetas.includes('+arte')))throw Error('Bulk metadata missing');
          return {ok:true,authors:details.length};
        })().catch(e=>({ok:false,error:e.message,stack:e.stack}))"""
        window.evaluate_js(script,callback=lambda value:(result.update(value),done.set()))
        if not done.wait(15): result.update(ok=False,error='JS timeout')
    except Exception as error: result.update(ok=False,error=str(error))
    finally: window.destroy()
with tempfile.TemporaryDirectory(prefix='balisco-bulk-') as temp:
    path=Path(temp)/'biblioteca.db'
    with closing(conectar(path)) as db,db:
        configurar(db,'id_perfil_drive','fixture')
        db.executemany("INSERT INTO items(drive_id,titulo,autor,tipo,ruta_relativa,perfil_drive) VALUES(?,?,?,?,?,?)",[(f'fixture_book_0{i}',f'Libro {i}',author,'pdf',f'{i}.pdf','fixture') for i,author in [(1,'Ana Torres'),(2,'Luis Vega')]])
    api=DesktopAPI(temp)
    window=webview.create_window('Bulk smoke',str(root/'ui/index.html'),js_api=api,width=1200,height=740,frameless=True,easy_drag=False)
    webview.start(run,window,gui='edgechromium',private_mode=True)
    print(json.dumps(result,ensure_ascii=False))
    assert result.get('ok'),result
