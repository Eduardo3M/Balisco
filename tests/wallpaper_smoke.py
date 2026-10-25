"""Exercise wallpaper selection and upload in a real WebView2 window with isolated data."""
import json
import sys
import tempfile
import threading
import time
from contextlib import closing
from pathlib import Path

import webview

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.database import conectar
from core.desktop_api import DesktopAPI

RESULT = {}


def run(window, api):
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if window.evaluate_js("Boolean(window.balisco?.state && window.pywebview?.api)"):
                break
            time.sleep(.05)
        script = r"""(async () => {
          const $ = id => document.getElementById(id);
          const wait = async test => { for (let i=0;i<100;i++) { if (test()) return; await new Promise(r=>setTimeout(r,50)); } throw Error('Timed out'); };
          const canvas=document.createElement('canvas'); canvas.width=40; canvas.height=40;
          canvas.getContext('2d').fillStyle='#e03020'; canvas.getContext('2d').fillRect(0,0,40,40);
          const blob=await new Promise(r=>canvas.toBlob(r,'image/png'));
          const data=await new Promise(r=>{const reader=new FileReader();reader.onload=()=>r(reader.result.split(',')[1]);reader.readAsDataURL(blob);});
          const saved=await pywebview.api.call('save_wallpaper',{name:'smoke.png',data});
          if (!saved.ok) throw Error(saved.error);
          $('wallpaper').click(); await wait(()=>$('popover').querySelector('[data-wp="smoke.png"]'));
          const handler=typeof $('popover').onclick;
          $('popover').querySelector('[data-wp="smoke.png"]').click();
          await wait(()=>document.body.classList.contains('has-wallpaper'));
          const selection={handler,state:window.balisco.state.wallpaper,hasWallpaper:document.body.classList.contains('has-wallpaper'),background:$('wallpaperBackdrop').style.backgroundImage.slice(0,60),rect:$('wallpaperBackdrop').getBoundingClientRect().toJSON(),stack:document.elementFromPoint(400,400)?.id,toast:$('toast').textContent,apiOk:(await pywebview.api.call('get_wallpaper',{filename:'smoke.png'})).ok};
          let pickerClicks=0; const picker=$('wallpaperFile'),nativeClick=picker.click;
          picker.click=()=>{pickerClicks++};
          $('popover').querySelector('#uploadWp').click();
          picker.click=nativeClick;
          if(pickerClicks!==1)throw Error('Upload button did not open file picker');
          const file=new File([blob],'upload.png',{type:'image/png'}),transfer=new DataTransfer();transfer.items.add(file);
          $('wallpaperFile').files=transfer.files;$('wallpaperFile').dispatchEvent(new Event('change',{bubbles:true}));
          await wait(()=>window.balisco.state.wallpaper==='upload.png');
          await wait(()=>$('popover').querySelector('[data-wp="upload.png"]'));
          $('popover').querySelector('[data-wp="upload.png"]').dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:100,clientY:100}));
          await wait(()=>!$('wallpaperContextMenu').hidden);
          $('wallpaperContextMenu').querySelector('[data-wallpaper-center]').click();
          await wait(()=>$('wallpaperBackdrop').style.backgroundPosition==='left top');
          const positions=JSON.parse((await pywebview.api.call('bootstrap',{})).data.prefs.wallpaper_positions);
          if(positions['upload.png']!==false)throw Error('Wallpaper position was not saved');
          $('popover').querySelector('[data-wp="upload.png"]').dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:100,clientY:100}));
          $('wallpaperContextMenu').querySelector('[data-wallpaper-delete]').click();
          await wait(()=>window.balisco.state.wallpaper===''&&!$('popover').querySelector('[data-wp="upload.png"]'));
          return {selection,pickerClicks,centered:positions['upload.png'],deleted:true,toast:$('toast').textContent};
        })().catch(e=>({error:e.message,stack:e.stack}))"""
        done = threading.Event()
        result = {}
        window.evaluate_js(script, callback=lambda value: (result.update(value), done.set()))
        if not done.wait(10):
            result['error'] = 'Timed out waiting for JavaScript'
        RESULT.update(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        window.destroy()


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='balisco-wallpaper-') as tmp:
        with closing(conectar(Path(tmp)/'biblioteca.db')):
            pass
        api = DesktopAPI(tmp)
        window = webview.create_window('Balisco wallpaper test', str(ROOT/'ui'/'index.html'), js_api=api, width=1000, height=700)
        webview.start(run, (window, api), gui='edgechromium', private_mode=True)
        if RESULT.get('error') or RESULT.get('pickerClicks') != 1 or RESULT.get('selection', {}).get('state') != 'smoke.png' or RESULT.get('centered') is not False or not RESULT.get('deleted'):
            sys.exit(1)
