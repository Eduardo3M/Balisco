"""Real WebView2 chrome/close regression test with an isolated database."""
from contextlib import closing
import importlib.machinery
import json
from pathlib import Path
import sys
import tempfile
import time
import ctypes

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.database import conectar, configurar
from core.desktop_api import DesktopAPI
import webview

launcher = importlib.machinery.SourceFileLoader('balisco_launcher', str(ROOT/'Balisco.pyw')).load_module()
result = {}


def run(window):
    try:
        deadline = time.monotonic() + 20
        while not window.evaluate_js('Boolean(window.balisco?.state.items.length)'):
            if time.monotonic() > deadline:
                raise AssertionError('Bootstrap timeout')
            time.sleep(.05)
        done = __import__('threading').Event()
        script = """(async()=>{
          const wait=async fn=>{const end=performance.now()+4000;while(!fn()){if(performance.now()>end)throw Error('Timeout');await new Promise(r=>setTimeout(r,20));}};
          document.querySelector('.card').click();await wait(()=>window.balisco.state.selected);
          const notes=document.getElementById('notes');notes.value='persist before close';notes.dispatchEvent(new Event('input'));
          return true;
        })()"""
        window.evaluate_js(script, callback=lambda value: done.set())
        assert done.wait(6)
        if '--facets' in sys.argv:
            done.clear()
            facet_js = """(async()=>{
              const S=window.balisco.state,$=id=>document.getElementById(id);
              const wait=async f=>{const end=performance.now()+4000;while(!f()){if(performance.now()>end)throw Error('Filter timeout');await new Promise(r=>setTimeout(r,20));}};
              const choose=(id,selector)=>{$(id).click();$('popover').querySelector(selector).click();};
              choose('rating','[data-rating="4"]');await wait(()=>S.tokens.includes('@rating:4'));
              choose('rating','[data-rating="4"]');await wait(()=>!S.tokens.some(t=>t.startsWith('@rating:')));
              choose('type','[data-type="pdf"]');await wait(()=>S.tokens.includes('@tipo:pdf'));
              choose('type','[data-type="curso"]');await wait(()=>S.tokens.includes('@tipo:curso')&&!S.tokens.includes('@tipo:pdf'));
              choose('type','[data-type="curso"]');await wait(()=>!S.tokens.some(t=>t.startsWith('@tipo:')));
              choose('statusFilter','[data-reading="interesado"]');await wait(()=>S.tokens.includes('@interesado'));
              choose('statusFilter','[data-reading="interesado"]');await wait(()=>!S.tokens.includes('@interesado'));
              $('favorite').click();await wait(()=>S.tokens.includes('@favoritos'));
              $('favorite').click();await wait(()=>!S.tokens.includes('@favoritos'));
              $('searchToggle').click();$('ghost').value='@leido';$('ghost').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
              await wait(()=>S.tokens.includes('@leido')&&$('statusFilter').querySelector('.state-indicator.leido'));
              $('searchToggle').click();$('ghost').value='@rating:3';$('ghost').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
              await wait(()=>S.tokens.includes('@rating:3')&&$('rating').querySelector('.rating-fill').style.width==='60%');
              $('searchToggle').click();$('ghost').value='@tipo:pdf';$('ghost').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
              await wait(()=>S.tokens.includes('@tipo:pdf')&&$('type').innerHTML.includes('<path'));
              $('searchToggle').click();$('ghost').value='@tipo:video';$('ghost').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
              await wait(()=>S.tokens.includes('@tipo:video')&&$('type').innerHTML.includes('<rect'));
              if($('type').getAttribute('aria-label')!=='Tipo: Videos')throw Error('Recent type indicator');
              const spin=(id,deltaY)=>$(id).dispatchEvent(new WheelEvent('wheel',{deltaY,bubbles:true,cancelable:true}));
              spin('statusFilter',-100);await wait(()=>$('statusFilter').querySelector('.state-indicator.abandonado'));
              spin('statusFilter',100);await wait(()=>$('statusFilter').querySelector('.state-indicator.leido'));
              spin('statusFilter',100);await wait(()=>$('statusFilter').querySelector('.state-indicator.leyendo'));
              spin('rating',-100);await wait(()=>$('rating').querySelector('.rating-fill').style.width==='80%');
              spin('rating',100);await wait(()=>$('rating').querySelector('.rating-fill').style.width==='60%');
              spin('type',100);await wait(()=>$('type').getAttribute('aria-label')==='Tipo: Cursos');
              spin('favorite',-100);await wait(()=>$('favorite').getAttribute('aria-pressed')==='true');
              spin('favorite',100);await wait(()=>$('favorite').getAttribute('aria-pressed')==='false');
              return ['rating','type','status','favorite'].every(x=>true);
            })().catch(e=>({error:e.message}))"""
            def facet_done(value):
                result['facets'] = value
                done.set()
            window.evaluate_js(facet_js, callback=facet_done)
            assert done.wait(12) and result['facets'] is True, result.get('facets')
        if '--gestures' in sys.argv:
            user32 = ctypes.windll.user32
            user32.SetProcessDPIAware()
            window.evaluate_js("window._gesture={down:0,move:0};window.addEventListener('mousedown',()=>_gesture.down++);window.addEventListener('mousemove',()=>_gesture.move++)")
            window.on_top = True
            user32.SetForegroundWindow(api._chrome.resolve())
            time.sleep(.2)
            def gesture(x, y, dx, dy, hold=0, steps=8, delay=.04):
                user32.SetCursorPos(x, y)
                time.sleep(.12)
                user32.mouse_event(0x0002, 0, 0, 0, 0)
                time.sleep(.25)
                for step in range(1, steps+1):
                    user32.SetCursorPos(x + dx*step//steps, y + dy*step//steps)
                    time.sleep(delay)
                if hold: time.sleep(hold)
                user32.mouse_event(0x0004, 0, 0, 0, 0)
                time.sleep(.25)
            class Rect(ctypes.Structure):
                _fields_=[('left',ctypes.c_long),('top',ctypes.c_long),('right',ctypes.c_long),('bottom',ctypes.c_long)]
            rect=Rect();user32.GetWindowRect(api._chrome.resolve(),ctypes.byref(rect))
            x,y,w,h=rect.left,rect.top,rect.right-rect.left,rect.bottom-rect.top
            gesture(x+11, y+27, 80, 0)
            after=Rect();user32.GetWindowRect(api._chrome.resolve(),ctypes.byref(after))
            assert after.left >= x+40, ('drag failed', (x,y), (after.left,after.top), window.evaluate_js('window._gesture'), user32.GetForegroundWindow(), api._chrome.resolve())
            result['drag'] = True
            rect=after;x,y,w,h=rect.left,rect.top,rect.right-rect.left,rect.bottom-rect.top
            gesture(x+w-2, y+h//2, 80, 0)
            after=Rect();user32.GetWindowRect(api._chrome.resolve(),ctypes.byref(after))
            assert after.right-after.left >= w+40, ('resize failed', w, after.right-after.left, window.evaluate_js('window._gesture'))
            result['resize'] = True
            if '--snap' in sys.argv:
                rect=after;x,y,w,h=rect.left,rect.top,rect.right-rect.left,rect.bottom-rect.top
                user32.SetCursorPos(x+50,0)
                api._chrome.snap()
                point=ctypes.wintypes.POINT();user32.GetCursorPos(ctypes.byref(point));after_snap=Rect();user32.GetWindowRect(api._chrome.resolve(),ctypes.byref(after_snap))
                assert user32.IsZoomed(api._chrome.resolve()), ('top-edge snap failed', (x,y,w,h), (point.x,point.y), (after_snap.left,after_snap.top,after_snap.right,after_snap.bottom))
                result['snap_top'] = True
                window.restore()
                time.sleep(.3)
        # Native changes must update the icon without clicking the JS button.
        for target in [True, False]:
            window.maximize() if target else window.restore()
            deadline = time.monotonic()+4
            while window.evaluate_js("document.getElementById('winMax').title") != ('Restaurar' if target else 'Maximizar'):
                assert time.monotonic()<deadline, 'Native maximize icon timeout'
                time.sleep(.02)
        result['native_maximize_restore'] = True
        result['close_started'] = time.monotonic()
        # Exercise native close (Alt+F4 path) while an edit is still pending.
        window.evaluate_js("document.getElementById('notes').value='last edit';document.getElementById('notes').dispatchEvent(new Event('input'))")
        if '--button' in sys.argv:
            window.evaluate_js("document.getElementById('winClose').click()")
        else:
            window.destroy()
    except Exception as exc:
        result['error'] = repr(exc)
        api._allow_close = True
        window.destroy()


with tempfile.TemporaryDirectory(prefix='balisco-chrome-') as tmp:
    path = Path(tmp)/'biblioteca.db'
    with closing(conectar(path)) as db, db:
        configurar(db, 'id_perfil_drive', 'fixture')
        db.execute("INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive) VALUES('fixture_book_01','Test','pdf','Test.pdf','fixture')")
    api = DesktopAPI(tmp)
    window = webview.create_window('Balisco chrome test', str(ROOT/'ui/index.html'), js_api=api,
                                   width=1000, height=700, min_size=(940,640), frameless=True, easy_drag=False)
    launcher.configure_close(window, api)
    webview.start(run, window, gui='edgechromium', private_mode=True)
    result['close_ms'] = round((time.monotonic()-result.get('close_started',time.monotonic()))*1000)
    with closing(conectar(path)) as db:
        result['saved_pending_edit'] = db.execute('SELECT notas FROM items').fetchone()[0] == 'last edit'
        result['geometry_saved'] = bool(db.execute("SELECT valor FROM configuracion WHERE clave='window_geometry'").fetchone())
    print(json.dumps(result), flush=True)
    assert not result.get('error') and result['saved_pending_edit'] and result['geometry_saved'], result
