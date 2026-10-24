"""Real WebView2 + JS bridge integration against an isolated fixture.
Run: python tests/webview_smoke.py
Never opens or modifies personal library files.
"""
import base64
from contextlib import closing
import json
import sqlite3
from unittest.mock import patch
from pathlib import Path
import sys
import tempfile
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.database import conectar, configurar
from core.desktop_api import DesktopAPI
import importlib
configure_close = importlib.import_module("Balisco").configure_close
import webview

ROOT=Path(__file__).resolve().parents[1]
RESULT={}
JS=r"""(async()=>{
 const $=id=>document.getElementById(id),S=window.balisco.state;
 const wait=async(test,label)=>{const end=performance.now()+6000;while(!test()){if(performance.now()>end)throw Error('Timeout: '+label);await new Promise(r=>setTimeout(r,25));}};
 const assert=(v,label)=>{if(!v)throw Error(label);};
 await wait(()=>S.items.length===1500,'bootstrap');
 await wait(()=>document.querySelector('.card'),'first card rendered');
 const initialCards=document.querySelectorAll('.card').length;
 assert(initialCards<50,'virtual grid bound');
 document.querySelector('.card').click();await wait(()=>S.selected,'selection');
 const id=S.selected.drive_id;
 $('notes').value='Nota astronomia';$('notes').dispatchEvent(new Event('input'));
 $('author').value='Lauricella';$('author').dispatchEvent(new Event('input'));
 await new Promise(r=>setTimeout(r,650));await window.balisco.flush();
 let detail=(await pywebview.api.call('detail',{id})).data;
 assert(detail.notas==='Nota astronomia'&&detail.autor==='Lauricella','autosave author + notes');
 document.activeElement.blur();
 document.dispatchEvent(new KeyboardEvent('keydown',{key:'L',bubbles:true}));
 assert(!$('ghost').hidden,'ghost appears');$('ghost').value='Lauricella';$('ghost').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));
 await wait(()=>S.items.length===1,'unified author filter');
 assert(S.tokens[0]==='Lauricella','live chip');
 document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
 await wait(()=>S.items.length===1500,'escape clears');
 $('rating').click();assert(!$('popover').hidden,'rating popover');$('popover').querySelector('[data-rating="4"]').click();
 await wait(()=>S.tokens.includes('@rating:4')&&S.items.length===0,'rating filter');
 document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await wait(()=>S.items.length===1500,'reset');
 document.querySelector('.card').click();await wait(()=>S.selected?.drive_id===id,'select');
 $('itemRating').querySelector('[data-rating="5"]').click();await wait(()=>S.selected.rating===5,'rating save');
 $('addTag').click();$('tagInput').value='anatomia';$('tagForm').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));
 await wait(()=>S.selected.etiquetas.includes('+anatomia'),'tag save');
 $('tags').click();await wait(()=>$('tagsView').textContent.includes('anatomia'),'tags hub');
 $('tagsView').querySelector('[data-tag="anatomia"]').click();await wait(()=>S.items.length===1&&S.view==='grid','tag filter');
 document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await wait(()=>S.items.length===1500,'reset tags');
 $('mode').click();await wait(()=>S.mode==='web','mode toggle');
 $('theme').click();await wait(()=>S.theme==='dark','theme');
 const zoom=S.zoom;$('zoom').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true,cancelable:true}));assert(S.zoom===zoom+10,'zoom keyboard');
 $('viewport').scrollTop=12000;$('viewport').dispatchEvent(new Event('scroll'));await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);
 assert(document.querySelectorAll('.card').length<60,'virtual grid while scrolling');
 // Pointer gestures use the same handlers with synthetic capture stubs.
 $('viewport').scrollTop=0;await new Promise(requestAnimationFrame);
 $('type').click();$('popover').querySelector('[data-type="pdf"]').click();await wait(()=>S.tokens.includes('@tipo:pdf')&&$('filters').querySelector('.chip'),'type');
 const chip=$('filters').querySelector('.chip');chip.dispatchEvent(new PointerEvent('pointerdown',{button:0,bubbles:true}));document.dispatchEvent(new PointerEvent('pointerup',{bubbles:true}));await wait(()=>S.tokens.length===0,'swipe delete');
 const priorZoom=S.zoom;$('zoom').setPointerCapture=()=>{};$('zoom').releasePointerCapture=()=>{};
 $('zoom').dispatchEvent(new PointerEvent('pointerdown',{button:0,clientX:100,pointerId:1}));$('zoom').dispatchEvent(new PointerEvent('pointermove',{clientX:150,pointerId:1}));$('zoom').dispatchEvent(new PointerEvent('pointerup',{clientX:150,pointerId:1}));assert(S.zoom===priorZoom+50,'zoom drag');
 $('dice').setPointerCapture=()=>{};$('dice').releasePointerCapture=()=>{};
 $('dice').dispatchEvent(new PointerEvent('pointerdown',{button:0,clientX:100,pointerId:2}));await new Promise(r=>setTimeout(r,180));$('dice').dispatchEvent(new PointerEvent('pointermove',{clientX:160,pointerId:2}));assert($('dice').classList.contains('target'),'hold swipe target');$('dice').dispatchEvent(new PointerEvent('pointerup',{clientX:160,pointerId:2}));await wait(()=>!$('dice').classList.contains('target'),'dice release');
 await new Promise(r=>setTimeout(r,200));await window.balisco.flush();
 const coverCanvas=document.createElement('canvas');coverCanvas.width=40;coverCanvas.height=60;const ctx=coverCanvas.getContext('2d');ctx.fillStyle='#456789';ctx.fillRect(0,0,40,60);const blob=await new Promise(r=>coverCanvas.toBlob(r,'image/png'));const file=new File([blob],'cover.png',{type:'image/png'});const transfer=new DataTransfer();transfer.items.add(file);$('hero').dispatchEvent(new DragEvent('drop',{dataTransfer:transfer,bubbles:true,cancelable:true}));await wait(()=>!!$('heroArt').querySelector('img'),'cover drag drop');
 const pinned=S.selected.drive_id;$('pin').click();document.querySelector('.card').click();await new Promise(r=>setTimeout(r,100));assert(S.selected.drive_id===pinned,'pinned selection');$('pin').click();
 // Course list is read from a local DriveFS fixture, never file contents.
 $('mode').click();await wait(()=>S.mode==='local','local mode');
 $('type').click();$('popover').querySelector('[data-type="curso"]').click();await wait(()=>S.items.length===1&&document.querySelector('.card'),'course filter');
 document.querySelector('.card').dispatchEvent(new MouseEvent('dblclick',{bubbles:true}));await wait(()=>S.view==='course'&&$('resources').textContent.includes('leccion.mp4'),'course resource list');
 assert(!$('courseView').querySelector('img'),'course has no thumbnails');$('back').click();document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await wait(()=>S.items.length===1500,'course return');
 const times=[];await new Promise(resolve=>{let last;function frame(t){$('viewport').scrollTop+=18;$('viewport').dispatchEvent(new Event('scroll'));if(last)times.push(t-last);last=t;if(times.length<100)requestAnimationFrame(frame);else resolve();}requestAnimationFrame(frame);});
 times.sort((a,b)=>a-b);
 return {ok:true,initialCards,scrolledCards:document.querySelectorAll('.card').length,rafMedianMs:times[50],rafP95Ms:times[94],checks:['bootstrap','virtualization','selection','notes + author autosave','unified FTS5','ghost input','rating filter','rating save','tags edit','tags hub','mode','theme','zoom','scroll','type filter','swipe delete','zoom drag','hold swipe target','cover drag drop','pin','course resource list']};
})().catch(e=>({ok:false,error:e.message,stack:e.stack}))"""

def run(window):
    try:
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            if window.evaluate_js('Boolean(window.balisco && window.pywebview && window.pywebview.api)'): break
            time.sleep(.05)
        done=threading.Event()
        def callback(result): RESULT.update(result if isinstance(result,dict) else {'result':result});done.set()
        window.evaluate_js(JS,callback=callback)
        if not done.wait(25): RESULT.update(ok=False,error='JS smoke timed out')
    except Exception as exc: RESULT.update(ok=False,error=str(exc))
    finally:
        print(json.dumps(RESULT,ensure_ascii=False),flush=True)
        (ROOT/'tests'/'webview-result.json').write_text(json.dumps(RESULT,indent=2),encoding='utf-8')
        window.evaluate_js("document.getElementById('notes').value='Saved on close';document.getElementById('notes').dispatchEvent(new Event('input'))")
        window.destroy()

with tempfile.TemporaryDirectory(prefix='balisco-ui-test-') as tmp:
    with closing(conectar(Path(tmp)/'biblioteca.db')) as db:
        with db:
            configurar(db,'id_perfil_drive','fixture')
            db.executemany("INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive) VALUES(?,?,'pdf',?,'fixture')",[(f'fixture_id_{i:05}',f'Libro {i:05}',f'Mi unidad\\Biblioteca\\{i}.pdf') for i in range(1500)])
            db.execute("UPDATE items SET tipo='curso',titulo='Curso de prueba' WHERE drive_id='fixture_id_01499'")
    metadata=Path(tmp)/'metadata_sqlite_db'
    with closing(sqlite3.connect(metadata)) as source:
        source.executescript('CREATE TABLE items(stable_id INTEGER PRIMARY KEY,local_title TEXT,is_folder INT,mime_type TEXT,file_size INT,trashed INT,proto BLOB); CREATE TABLE stable_parents(item_stable_id INT,parent_stable_id INT);')
        with source:
            for i,title,folder,parent,drive_id in [(1,'Mi unidad',1,None,'fixture_root_01'),(2,'Biblioteca',1,1,'fixture_library'),(3,'Curso de prueba',1,2,'fixture_id_01499'),(4,'leccion.mp4',0,3,'fixture_resource_01')]:
                raw=drive_id.encode()
                source.execute('INSERT INTO items VALUES(?,?,?,?,?,?,?)',(i,title,folder,'video/mp4',512,0,bytes([10,len(raw)])+raw))
                if parent:source.execute('INSERT INTO stable_parents VALUES(?,?)',(i,parent))
    api=DesktopAPI(tmp)
    window=webview.create_window('Balisco · Prueba aislada',str(ROOT/'ui'/'index.html'),js_api=api,width=1100,height=800)
    configure_close(window,api)
    webview.settings['OPEN_DEVTOOLS_IN_DEBUG']=False
    with patch('core.desktop_api.detectar_perfiles_drive',return_value=[{'id':'fixture','ruta_db':str(metadata),'tiene_biblioteca':True}]):
        webview.start(run,window,gui='edgechromium',debug=True)
    with closing(api._connect()) as db:
        RESULT['closeFlush']=bool(db.execute("SELECT 1 FROM items WHERE notas='Saved on close'").fetchone())
    RESULT['ok']=RESULT.get('ok') and RESULT['closeFlush']
    (ROOT/'tests'/'webview-result.json').write_text(json.dumps(RESULT,indent=2),encoding='utf-8')
    print('closeFlush:',RESULT['closeFlush'],flush=True)
sys.exit(0 if RESULT.get('ok') else 1)
