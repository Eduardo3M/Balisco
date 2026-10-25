"""Exercise explorer layout, scoped search, and reused inspector in WebView2."""
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
            if window.evaluate_js('window.balisco?.state.items.length > 0 && document.querySelector(".card")'):
                break
            time.sleep(.05)
        script = r"""(async()=>{
          const $=id=>document.getElementById(id);
          const wait=async test=>{for(let i=0;i<100;i++){if(test())return;await new Promise(r=>setTimeout(r,40));}throw Error('Timed out '+JSON.stringify({view:window.balisco?.state.view,count:$('resources')?.querySelectorAll('[data-resource-key]').length,toast:$('toast')?.textContent}));};
          const original=pywebview.api.call.bind(pywebview.api);
          pywebview.api.call=async(action,payload)=>{
            if(action==='container_view')return {ok:true,data:{view:'grid'}};
            if(action==='container')return {ok:true,data:[
              {id:'fixture_folder',title:'Unidad',folder:true,size:0,mime:'application/vnd.google-apps.folder'},
              {id:'fixture_file',title:'Unidad/Leccion.pdf',folder:false,size:1024,mime:'application/pdf'},
              {id:'fixture_other',title:'Otro.txt',folder:false,size:100,mime:'text/plain'}]};
            if(action==='container_resource_detail')return {ok:true,data:{id:payload.id,title:'Unidad/Leccion.pdf',size:1024,mime:'application/pdf',folder:false,item:{titulo:'Leccion.pdf',notas:'',autor:'',etiquetas:'',rating:0,es_favorito:0,estado_lectura:'pendiente'}}};
            if(action==='container_indexed_ids')return {ok:true,data:['fixture_file']};
            if(action==='container_cover')return {ok:true,data:null};
            return original(action,payload);
          };
          const courseCard=[...document.querySelectorAll('.card')].find(card=>card.getAttribute('aria-label')==='Curso');
          if(!courseCard)throw Error('Course card unavailable: '+JSON.stringify(window.balisco.state.items.map(item=>item.titulo)));
          courseCard.dispatchEvent(new MouseEvent('dblclick',{bubbles:true}));
          await wait(()=>$('courseView').hidden===false && $('resources').querySelectorAll('[data-resource-key]').length===2);
          const rect=$('courseView').getBoundingClientRect(),bar=$('courseView').querySelector('.course-bar').getBoundingClientRect();
          if(Math.abs(rect.left-bar.left)>2||Math.abs(rect.right-bar.right)>2)throw Error('Header does not fill explorer width');
          if($('courseView').dataset.layout!=='grid')throw Error('Saved grid view not restored');if($('summary').textContent!=='3')throw Error('Root recursive count is incorrect: '+$('summary').textContent);$('resources').querySelector('[data-folder]').dispatchEvent(new MouseEvent('dblclick',{bubbles:true}));if($('summary').textContent!=='1')throw Error('Folder count is incorrect: '+$('summary').textContent);$('folderBack').click();if($('summary').textContent!=='3')throw Error('Parent count was not restored');const zoom=$('courseZoom'),levels=[];for(let level=0;level<4;level++){zoom.value=level;zoom.dispatchEvent(new Event('input'));levels.push({columns:Number(getComputedStyle($('courseView')).getPropertyValue('--course-columns')),filled:$('courseViewToggle').querySelectorAll('.course-grid-levels .is-filled').length});}if(levels.some((entry,index)=>entry.filled!==index+1)||levels.some((entry,index)=>index&&entry.columns<=levels[index-1].columns))throw Error('Grid zoom levels are not distinct: '+JSON.stringify(levels));const animated=$('resources').querySelector('.resource-card').getAnimations().length>0;
          $('searchToggle').click();$('ghost').value='Leccion';$('ghost').dispatchEvent(new Event('input'));
          await wait(()=>$('resources').querySelectorAll('[data-resource-key]').length===1);
          if(window.balisco.state.view!=='course')throw Error('Scoped search left explorer');
          $('resources').querySelector('[data-resource-key]').click();
          await wait(()=>$('details').hidden===false);
          if($('courseInspector').hidden!==true)throw Error('Original inspector was not reused');
          return {ok:true,layout:$('courseView').dataset.layout,headerWidth:bar.width,explorerWidth:rect.width,search:$('summary').textContent,inspector:$('details').hidden,zoomLevels:levels,zoomAnimated:animated};
        })().catch(e=>({ok:false,error:e.message,stack:e.stack}))"""
        done = threading.Event()
        window.evaluate_js(script, callback=lambda value: (RESULT.update(value), done.set()))
        if not done.wait(10):
            RESULT.update(ok=False, error='JavaScript timeout')
        if RESULT.get('ok'):
            window.resize(720, 660)
            time.sleep(.35)
            small = window.evaluate_js("""(()=>{const view=document.getElementById('courseView'),bar=view.querySelector('.course-bar');const a=view.getBoundingClientRect(),b=bar.getBoundingClientRect();return {aligned:Math.abs(a.left-b.left)<2&&Math.abs(a.right-b.right)<2,overflow:bar.scrollWidth>bar.clientWidth+2,columns:getComputedStyle(view).getPropertyValue('--course-columns').trim(),background:getComputedStyle(view).backgroundImage!=='none'};})()""")
            RESULT['smallWindow'] = small
            if not small['aligned'] or small['overflow'] or not small['background']:
                RESULT.update(ok=False, error='Explorer does not fit the small window')
            list_zoom = window.evaluate_js("""(()=>{const $=id=>document.getElementById(id);$('courseViewToggle').click();const mode=$('courseView').dataset.layout,slider=$('courseZoom');slider.value=4;slider.dispatchEvent(new Event('input'));const list={mode,rowHeight:$('resources').querySelector('.resource').getBoundingClientRect().height,sliderMax:slider.max,columns:getComputedStyle($('courseView')).getPropertyValue('--course-list-columns').trim()};$('courseViewToggle').click();return {...list,detailsMode:$('courseView').dataset.layout,detailsHasHeader:getComputedStyle($('courseView').querySelector('.table-head')).display!=='none',detailsSliderHidden:$('courseZoom').hidden,detailsRowHeight:$('resources').querySelector('.resource').getBoundingClientRect().height,detailsFullWidth:Math.abs($('courseView').getBoundingClientRect().left-$('courseView').querySelector('.table-head').getBoundingClientRect().left)<2&&Math.abs($('courseView').getBoundingClientRect().right-$('resources').querySelector('.resource').getBoundingClientRect().right)<2,detailsFlush:Math.abs($('courseView').querySelector('.course-bar').getBoundingClientRect().bottom-$('courseView').querySelector('.table-head').getBoundingClientRect().top)<2};})()""")
            RESULT['listZoom'] = list_zoom
            if list_zoom['mode'] != 'list' or list_zoom['rowHeight'] < 60 or list_zoom['sliderMax'] != '4' or list_zoom['detailsMode'] != 'details' or not list_zoom['detailsHasHeader'] or not list_zoom['detailsSliderHidden'] or list_zoom['detailsRowHeight'] != 52 or not list_zoom['detailsFullWidth'] or not list_zoom['detailsFlush']:
                RESULT.update(ok=False, error='List and details views are not distinct')
    except Exception as error:
        RESULT.update(ok=False, error=str(error))
    finally:
        window.destroy()


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='balisco-container-ui-') as temp:
        with closing(conectar(Path(temp) / 'biblioteca.db')) as db, db:
            configurar(db, 'id_perfil_drive', 'fixture')
            db.executemany(
                'INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive) VALUES(?,?,?,?,?)',
                [('fixture_course', 'Curso', 'curso', 'Curso', 'fixture'),
                 ('fixture_file', 'Leccion.pdf', 'pdf', 'Curso/Unidad/Leccion.pdf', 'fixture')],
            )
        api = DesktopAPI(temp)
        api._containers['fixture_course'] = {
            'fixture_file': {'id': 'fixture_file', 'title': 'Unidad/Leccion.pdf', 'folder': False},
            'fixture_folder': {'id': 'fixture_folder', 'title': 'Unidad', 'folder': True},
        }
        indexed = api.call('container_indexed_ids', {'container': 'fixture_course', 'ids': ['fixture_file', 'fixture_folder', 'fixture_other']})
        if not indexed['ok'] or indexed['data'] != ['fixture_file']:
            raise AssertionError(indexed)
        window = webview.create_window('Container UI test', str(ROOT / 'ui' / 'index.html'), js_api=api, width=1100, height=750)
        webview.start(run, window, gui='edgechromium', private_mode=True)
        print(json.dumps(RESULT, ensure_ascii=False))
        if not RESULT.get('ok'):
            sys.exit(1)
