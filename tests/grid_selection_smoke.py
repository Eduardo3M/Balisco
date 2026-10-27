"""Check grid zoom and Ctrl selection in an isolated WebView2 window."""
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


def run(window):
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if window.evaluate_js('window.balisco?.state.items.length===12 && document.querySelectorAll(".card").length>=2'):
                break
            time.sleep(.05)
        script = r"""(async()=>{
          const $=id=>document.getElementById(id),S=window.balisco.state;
          const wait=async test=>{for(let i=0;i<100;i++){if(test())return;await new Promise(r=>setTimeout(r,30));}throw Error('Timed out');};
          const v=$('viewport'),cards=[...document.querySelectorAll('.card')];
          if(cards[0].querySelector('.cover .badge'))throw Error('Type badge remains on cover');
          const meta=cards[0].querySelector('.card-meta');
          if(!meta?.firstElementChild?.classList.contains('card-type')||!meta.children[1]?.classList.contains('card-size'))throw Error('Type is not before size');
          if(meta.firstElementChild.textContent.trim()!=='C')throw Error('Container type must be abbreviated C');
          const nativeCapture=v.setPointerCapture.bind(v);let captures=0;
          v.setPointerCapture=id=>{captures++;};
          const click=(card,id)=>{card.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,button:0,buttons:1,pointerId:id,ctrlKey:true}));card.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,button:0,pointerId:id,ctrlKey:true}));card.dispatchEvent(new MouseEvent('click',{bubbles:true,ctrlKey:true}));};
          click(cards[0],1);await wait(()=>S.bulkIds.size===1);
          click(cards[1],2);await wait(()=>S.bulkIds.size===2);
          if(captures!==0)throw Error('Ctrl+click captured pointer');
          click(cards[0],3);await wait(()=>S.bulkIds.size===1);
          cards[2].dispatchEvent(new MouseEvent('click',{bubbles:true}));
          await wait(()=>S.bulkIds.size===1);
          cards[5].dispatchEvent(new MouseEvent('click',{bubbles:true,shiftKey:true}));
          await wait(()=>S.bulkIds.size===4);
          if(!cards.slice(2,6).every(card=>S.bulkIds.has(S.items[Number(card.dataset.index)].drive_id)))throw Error('Shift range is incomplete');
          cards[7].dispatchEvent(new MouseEvent('click',{bubbles:true}));
          await wait(()=>S.bulkIds.size===1&&S.bulkIds.has(S.items[7].drive_id));
          v.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,button:0,buttons:1,pointerId:4,ctrlKey:true,clientX:10,clientY:100}));
          v.dispatchEvent(new PointerEvent('pointermove',{bubbles:true,button:0,buttons:1,pointerId:4,ctrlKey:true,clientX:30,clientY:120}));
          if(captures!==1)throw Error('Ctrl+drag did not capture pointer');
          v.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,button:0,pointerId:4,ctrlKey:true,clientX:30,clientY:120}));
          cards[0].dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,button:0,buttons:1,pointerId:5,clientX:10,clientY:100}));
          v.dispatchEvent(new PointerEvent('pointermove',{bubbles:true,button:0,buttons:1,pointerId:5,clientX:300,clientY:220}));
          if(captures!==2)throw Error('Plain drag did not capture pointer');
          await new Promise(requestAnimationFrame);
          v.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,button:0,pointerId:5,clientX:300,clientY:220}));
          if(!S.bulkIds.size||S.bulkIds.has(S.items[7].drive_id))throw Error('Plain drag did not replace selection');
          v.dispatchEvent(new MouseEvent('click',{bubbles:true}));
          if(!S.bulkIds.size)throw Error('Drag release cleared selection');
          await new Promise(r=>setTimeout(r,0));
          const selectedCount=S.bulkIds.size;
          $('inspector').dispatchEvent(new MouseEvent('click',{bubbles:true}));
          if(S.bulkIds.size!==selectedCount)throw Error('Inspector click cleared selection');
          v.dispatchEvent(new MouseEvent('click',{bubbles:true}));
          if(S.bulkIds.size||S.selected)throw Error('Empty area did not clear selection');
          const rightClick=target=>{target.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,button:2,pointerId:8}));target.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,button:2,clientX:130,clientY:160}));};
          rightClick(cards[0]);await wait(()=>$('popover').classList.contains('item-actions')&&!$('popover').hidden);
          rightClick($('popover'));
          if($('popover').hidden||!$('popover').classList.contains('is-closing')||getComputedStyle($('popover')).animationName!=='appear'||getComputedStyle($('popover')).animationDirection!=='reverse')throw Error('Context menu does not reverse its entrance animation');
          let fading=false;
          for(let i=0;i<9;i++){await new Promise(r=>setTimeout(r,20));const opacity=Number(getComputedStyle($('popover')).opacity);if(opacity>0&&opacity<1){fading=true;break;}}
          if(!fading)throw Error('Context menu never showed an intermediate opacity');
          rightClick(cards[0]);await wait(()=>$('popover').classList.contains('item-actions')&&!$('popover').classList.contains('is-closing')&&!$('popover').hidden);
          rightClick(cards[0]);await wait(()=>$('popover').hidden);
          cards[1].dispatchEvent(new MouseEvent('click',{bubbles:true}));
          await wait(()=>$('containerProperty'));
          v.setPointerCapture=nativeCapture;
          const levels=new Set([$('zoom').dataset.columns]);
          for(let i=0;i<12;i++){$('zoom').click();const columns=$('zoom').dataset.columns;levels.add(columns);const visible=S.rows.values().next().value;if(visible.querySelector('.card-type').textContent.trim().length!==1)throw Error('Type expanded at zoom '+columns);const lines=getComputedStyle(visible.querySelector('.card-title')).webkitLineClamp;if(lines!==(Number(columns)>=4?'3':'2'))throw Error('Wrong title space at zoom '+columns+': '+lines);}
          if(levels.size!==4||levels.has('1'))throw Error('Expected exactly four zoom levels without one-column view: '+[...levels]);
          while($('zoom').dataset.columns!=='5')$('zoom').click();
          const narrow=S.rows.values().next().value;
          if(narrow.querySelector('.card-type').textContent.trim().length!==1)throw Error('Type expanded on narrow card');
          const press=button=>{button.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,button:0,pointerId:20}));button.click();};
          const toggle=async id=>{const button=$(id);if(!button)throw Error('Missing button '+id);press(button);try{await wait(()=>!$('popover').hidden);}catch{throw Error('Popover did not open: '+id);}press(button);try{await wait(()=>$('popover').hidden);}catch{throw Error('Popover did not close: '+id);}};
          for(const id of ['rating','statusFilter','type','sort','wallpaper','driveTools'])await toggle(id);
          press($('statusFilter'));await wait(()=>!$('popover').hidden);
          const pending=getComputedStyle($('popover').querySelector('.state-indicator.pendiente')).backgroundColor;
          if(pending==='rgba(0, 0, 0, 0)'||pending==='transparent')throw Error('Pending state is not gray');
          press($('statusFilter'));await wait(()=>$('popover').hidden);
          cards[1].dispatchEvent(new MouseEvent('click',{bubbles:true}));await wait(()=>$('containerProperty'));
          await toggle('containerProperty');
          $('addTag').click();if($('tagForm').hidden)throw Error('Tag form did not open');$('addTag').click();if(!$('tagForm').hidden)throw Error('Tag form did not close');
          $('addAuthor').click();if($('authorForm').hidden)throw Error('Author form did not open');$('addAuthor').click();if(!$('authorForm').hidden)throw Error('Author form did not close');
          $('searchToggle').click();if($('ghost').hidden)throw Error('Search did not open');$('searchToggle').click();await wait(()=>$('ghost').hidden);
          $('metadata').click();await wait(()=>S.view==='metadata');$('metadata').click();await wait(()=>S.view==='grid');
          return {ok:true,levels:[...levels],ctrlClickSelection:true,shiftRange:true,plainDrag:true,outsideClickClears:true,inspectorPreserves:true,repeatedRightClickCloses:true,popovers:7,pending,searchAndMetadata:true};
        })().catch(e=>({ok:false,error:e.message,stack:e.stack}))"""
        done = threading.Event()
        window.evaluate_js(script, callback=lambda value: (RESULT.update(value), done.set()))
        if not done.wait(10):
            RESULT.update(ok=False, error='JavaScript timeout')
        print(json.dumps(RESULT, ensure_ascii=False), flush=True)
    finally:
        window.destroy()


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='balisco-grid-') as temp:
        with closing(conectar(Path(temp)/'biblioteca.db')) as db, db:
            configurar(db, 'id_perfil_drive', 'fixture')
            db.executemany('INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive) VALUES(?,?,?,?,?)',
                           [(f'fixture_book_{i:02}', f'Libro {i}', 'curso' if i == 11 else 'pdf', f'{i}.pdf', 'fixture') for i in range(12)])
        api = DesktopAPI(temp)
        window = webview.create_window('Grid selection test', str(ROOT/'ui'/'index.html'), js_api=api, width=1100, height=750)
        webview.start(run, window, gui='edgechromium', private_mode=True)
        if not RESULT.get('ok'):
            sys.exit(1)
