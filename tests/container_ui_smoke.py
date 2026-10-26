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
          const wait=async test=>{for(let i=0;i<100;i++){if(test())return;await new Promise(r=>setTimeout(r,40));}throw Error('Timed out '+JSON.stringify({view:window.balisco?.state.view,count:$('resources')?.querySelectorAll('[data-resource-key]').length,toast:$('toast')?.textContent,popover:$('popover')?.className,hidden:$('popover')?.hidden}));};
          const original=pywebview.api.call.bind(pywebview.api);
          const inspector=$('inspector'),toggle=$('inspectorToggle'),expandedWidth=inspector.getBoundingClientRect().width,expandedCatalogWidth=$('viewport').getBoundingClientRect().width;
          if(toggle.nextElementSibling!==$('winMin')||toggle.parentElement!==$('winMin').parentElement||inspector.contains(toggle)||$('inspectorEmpty').textContent.trim())throw Error('Inspector toggle or empty state is in the wrong place');
          if(Math.abs(toggle.getBoundingClientRect().width-$('winMin').getBoundingClientRect().width)>1||Math.abs(toggle.querySelector('svg').getBoundingClientRect().width-$('winMin').querySelector('svg').getBoundingClientRect().width)>1)throw Error('Inspector toggle does not match window controls');
          toggle.click();await new Promise(resolve=>setTimeout(resolve,450));
          if(!inspector.classList.contains('is-compact')||inspector.getBoundingClientRect().width>3||$('viewport').getBoundingClientRect().width-expandedCatalogWidth<expandedWidth-4||!$('details').inert||toggle.getAttribute('aria-expanded')!=='false'||!toggle.classList.contains('is-compact'))throw Error('Library inspector still occupies card space');
          toggle.click();await new Promise(resolve=>setTimeout(resolve,450));
          if(Math.abs(inspector.getBoundingClientRect().width-expandedWidth)>2||$('details').inert||toggle.getAttribute('aria-expanded')!=='true')throw Error('Library inspector did not expand');
          pywebview.api.call=async(action,payload)=>{
            if(action==='container_view')return {ok:true,data:{view:'grid'}};
            if(action==='container')return {ok:true,data:[
              {id:'fixture_folder',title:'Unidad',folder:true,size:0,mime:'application/vnd.google-apps.folder',es_favorito:1,rating:4,autor:'Marcelo'},
              {id:'fixture_file',title:'Unidad/Leccion.pdf',folder:false,size:1024,mime:'application/pdf',fijado:1,es_favorito:1,rating:5,autor:'Marcelo',ultimo_acceso:'2026-01-01'},
              {id:'fixture_other',title:'Otro.txt',folder:false,size:100,mime:'text/plain'}]};
            if(action==='container_resource_detail')return {ok:true,data:{id:payload.id,title:'Unidad/Leccion.pdf',size:1024,mime:'application/pdf',folder:false,item:{titulo:'Leccion.pdf',notas:'',autor:'',etiquetas:'',rating:0,es_favorito:0,estado_lectura:'pendiente'}}};
            if(action==='container_indexed_ids')return {ok:true,data:['fixture_file']};
            if(action==='container_cover')return {ok:true,data:null};
            return original(action,payload);
          };
          $('statusFilter').click();const stateMenu=$('popover'),stateRect=stateMenu.getBoundingClientRect();
          if(stateRect.left<7||stateRect.right>innerWidth-7||stateMenu.querySelectorAll('.state-choice').length!==6)throw Error('Reading states menu is clipped');
          $('statusFilter').click();
          $('sort').click();if($('popover').querySelector('[data-sort]:last-child')?.dataset.sort!=='natural'||$('popover').querySelector('[data-sort="recientes"]')?.getAttribute('aria-current')!=='false')throw Error('Natural sort is missing or default order appears selected');
          $('popover').querySelector('[data-sort="peso"]').click();await wait(()=>window.balisco.state.tokens.includes('@orden:peso'));
          $('sort').click();$('popover').querySelector('[data-sort="natural"]').click();await wait(()=>!window.balisco.state.tokens.some(token=>token.startsWith('@orden:')));
          $('sort').click();if($('popover').querySelector('[data-sort][aria-current="true"]'))throw Error('Natural order still highlights a sort option');$('sort').click();
          await wait(()=>[...document.querySelectorAll('.card')].some(card=>card.getAttribute('aria-label')?.startsWith('Curso')));
          const courseCard=[...document.querySelectorAll('.card')].find(card=>card.getAttribute('aria-label')?.startsWith('Curso'));
          if(!courseCard)throw Error('Course card unavailable: '+JSON.stringify(window.balisco.state.items.map(item=>item.titulo)));
          if(!courseCard.querySelector('.card-pin svg'))throw Error('Pinned library card has no pin in its upper left corner');
          if(courseCard.querySelector('.card-state')||getComputedStyle(courseCard.querySelector('.card-info'),'::after').content==='none')throw Error('Reading state is not a gradient below the cover');
          courseCard.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,clientX:180,clientY:220}));
          await wait(()=>$('popover').classList.contains('item-actions')&&!$('popover').hidden);
          const menu=$('popover'),menuRect=menu.getBoundingClientRect();
          if(!menu.querySelector('[data-item-action="pin"] svg'))throw Error('Pin action has no pin icon');
          const stateButtons=[...menu.querySelectorAll('.item-actions-states button')],stateBounds=stateButtons.map(button=>button.getBoundingClientRect());
          if(Math.abs((stateBounds[0].left+stateBounds.at(-1).right)/2-(menuRect.left+menuRect.right)/2+3)>2)throw Error('Reading state dots are visually off center');
          const ratingBounds=[...menu.querySelectorAll('.item-actions-rating button')].map(button=>button.getBoundingClientRect());
          if(stateBounds.some((bounds,index)=>Math.abs((bounds.left+bounds.right-ratingBounds[index].left-ratingBounds[index].right)/2)>1))throw Error('Reading state dots and rating stars do not share columns');
          for(const button of menu.querySelectorAll('.item-actions-rating button,.item-actions-states button')){const box=button.getBoundingClientRect(),symbol=button.querySelector('svg,.state-indicator').getBoundingClientRect();if(Math.abs((box.left+box.right-symbol.left-symbol.right)/2)>1||Math.abs((box.top+box.bottom-symbol.top-symbol.bottom)/2)>1)throw Error('Icon is off center inside its highlight');}
          if(Math.abs(menuRect.left-180)>4||Math.abs(menuRect.top-220)>4||menuRect.width>205||!menu.querySelector('[data-item-action="visible"]')||menu.querySelector('[data-item-action="visible"] .item-action-check')||menu.querySelector('[data-item-action="favorite"]')?.textContent!=='Quitar de favoritos'||menu.querySelectorAll('.item-actions-rating .on').length!==5||menu.querySelector('[data-item-state="abandonado"]')?.getAttribute('aria-pressed')!=='true'||menu.querySelector('.item-actions-heading'))throw Error('Context menu does not reflect saved properties or is too wide');
          if(!menu.querySelector('[data-item-action="open-panel"] svg'))throw Error('Context menu lacks Open panel');
          toggle.click();await new Promise(resolve=>setTimeout(resolve,450));
          menu.querySelector('[data-item-action="open-panel"]').click();await new Promise(resolve=>setTimeout(resolve,450));
          if(inspector.classList.contains('is-compact'))throw Error('Context menu did not open the inspector');
          courseCard.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,clientX:180,clientY:220}));
          await wait(()=>$('popover').classList.contains('item-actions')&&!$('popover').hidden);
          $('popover').querySelector('[data-item-rating="5"]').click();
          await wait(()=>window.balisco.state.items.find(item=>item.drive_id==='fixture_course')?.rating===0);
          await wait(()=>[...document.querySelectorAll('.card')].some(card=>card.getAttribute('aria-label')?.startsWith('Curso')));
          window.balisco.state.bulkIds=new Set(['fixture_course','fixture_extra']);
          [...document.querySelectorAll('.card')].find(card=>card.getAttribute('aria-label')?.startsWith('Curso')).dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,clientX:180,clientY:220}));
          await wait(()=>$('popover').classList.contains('item-actions')&&!$('popover').hidden);
          if($('popover').querySelector('.item-action-row[data-item-action="favorite"]').classList.contains('is-active')||$('popover').querySelector('.item-actions-rating .on')||$('popover').querySelector('.item-actions-states [aria-pressed="true"]'))throw Error('Mixed bulk selection copied one item properties');
          const recentAction=$('popover').querySelector('[data-item-action="remove-recent"]');if(!recentAction||recentAction.querySelector('svg path')?.getAttribute('d')?.startsWith('M14 2H5'))throw Error('Bulk remove from Recents lacks its history icon');
          $('popover').querySelector('[data-item-action="remove-recent"]').click();
          for(let i=0;i<100;i++){if((await original('selection_properties',{ids:['fixture_course','fixture_extra']})).data.recent_count===0)break;await new Promise(resolve=>setTimeout(resolve,40));}
          if((await original('selection_properties',{ids:['fixture_course','fixture_extra']})).data.recent_count!==0)throw Error('Bulk remove from Recents did not update both items');
          window.balisco.state.bulkIds.clear();
          await wait(()=>[...document.querySelectorAll('.card')].some(card=>card.getAttribute('aria-label')?.startsWith('Curso')));
          [...document.querySelectorAll('.card')].find(card=>card.getAttribute('aria-label')?.startsWith('Curso')).dispatchEvent(new MouseEvent('dblclick',{bubbles:true}));
          await wait(()=>$('courseView').hidden===false && $('resources').querySelectorAll('[data-resource-key]').length===2);
          toggle.click();await new Promise(resolve=>setTimeout(resolve,450));
          if(inspector.getBoundingClientRect().width>3||!$('courseInspector').inert||!$('details').inert)throw Error('Explorer inspector still occupies card space');
          $('resources').querySelector('[data-folder]').dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,clientX:190,clientY:240}));
          await wait(()=>$('popover').querySelector('[data-item-action="open-panel"]')&&!$('popover').hidden);
          $('popover').querySelector('[data-item-action="open-panel"]').click();await new Promise(resolve=>setTimeout(resolve,450));
          if(Math.abs(inspector.getBoundingClientRect().width-expandedWidth)>2||$('courseInspector').inert)throw Error('Explorer inspector did not expand');
          const rect=$('courseView').getBoundingClientRect(),bar=$('courseView').querySelector('.course-bar').getBoundingClientRect();
          if(Math.abs(rect.left-bar.left)>2||Math.abs(rect.right-bar.right)>2)throw Error('Header does not fill explorer width');
          if($('courseView').dataset.layout!=='grid')throw Error('Saved grid view not restored');
          if($('summary').textContent!=='3')throw Error('Root recursive count is incorrect: '+$('summary').textContent);
          const folderMeta=$('resources').querySelector('.folder-card .card-meta');
          if(!folderMeta?.querySelector('.card-type')||!folderMeta.querySelector('.card-size')||!folderMeta.querySelector('.favorite-mark')||!folderMeta.querySelector('.card-rating')||!folderMeta.querySelector('.card-author')||folderMeta.textContent.includes('archivos'))throw Error('Folder card does not match catalog metadata');
          const zoom=$('courseZoom');zoom.value=2;zoom.dispatchEvent(new Event('input'));
          $('resources').querySelector('[data-folder]').dispatchEvent(new MouseEvent('dblclick',{bubbles:true}));
          if($('summary').textContent!=='1'||$('courseView').dataset.layout!=='grid'||zoom.value!=='2')throw Error('New folder did not inherit root layout');
          $('courseViewToggle').click();zoom.value=4;zoom.dispatchEvent(new Event('input'));
          if($('courseView').dataset.layout!=='list'||zoom.value!=='4')throw Error('Folder list zoom was not set');
          $('courseViewToggle').click();
          if($('courseView').dataset.layout!=='details')throw Error('Folder details mode was not set');
          $('folderBack').click();
          if($('summary').textContent!=='3'||$('courseView').dataset.layout!=='grid'||zoom.value!=='2')throw Error('Root layout was overwritten by subfolder');
          $('resources').querySelector('[data-folder]').dispatchEvent(new MouseEvent('dblclick',{bubbles:true}));
          if($('courseView').dataset.layout!=='details')throw Error('Folder did not restore details mode');
          $('courseViewToggle').click();zoom.value=1;zoom.dispatchEvent(new Event('input'));
          $('courseViewToggle').click();
          if($('courseView').dataset.layout!=='list'||zoom.value!=='4')throw Error('Folder did not restore list zoom');
          $('folderBack').click();
          if($('courseView').dataset.layout!=='grid'||zoom.value!=='2')throw Error('Root grid zoom changed after visiting folder');
          const levels=[];for(let level=0;level<4;level++){zoom.value=level;zoom.dispatchEvent(new Event('input'));levels.push({columns:Number(getComputedStyle($('courseView')).getPropertyValue('--course-columns')),filled:$('courseViewToggle').querySelectorAll('.course-grid-levels .is-filled').length});}
          if(levels.some((entry,index)=>entry.filled!==index+1)||levels.some((entry,index)=>index&&entry.columns<=levels[index-1].columns))throw Error('Grid zoom levels are not distinct: '+JSON.stringify(levels));
          const animated=$('resources').querySelector('.resource-card').getAnimations().length>0;
          $('back').click();await wait(()=>$('courseView').hidden&&[...document.querySelectorAll('.card')].some(card=>card.getAttribute('aria-label')?.startsWith('Curso')));
          [...document.querySelectorAll('.card')].find(card=>card.getAttribute('aria-label')?.startsWith('Curso')).dispatchEvent(new MouseEvent('dblclick',{bubbles:true}));
          await wait(()=>$('courseView').hidden===false&&$('resources').querySelector('[data-folder]'));
          if($('courseView').dataset.layout!=='grid'||zoom.value!=='3')throw Error('Root zoom did not survive reopening container');
          $('resources').querySelector('[data-folder]').dispatchEvent(new MouseEvent('dblclick',{bubbles:true}));
          if($('courseView').dataset.layout!=='list'||zoom.value!=='4')throw Error('Folder layout did not survive reopening container');
          $('folderBack').click();
          $('courseViewToggle').click();
          $('back').click();await wait(()=>$('courseView').hidden&&[...document.querySelectorAll('.card')].some(card=>card.getAttribute('aria-label')?.startsWith('Curso')));
          [...document.querySelectorAll('.card')].find(card=>card.getAttribute('aria-label')?.startsWith('Curso')).dispatchEvent(new MouseEvent('dblclick',{bubbles:true}));
          await wait(()=>$('courseView').hidden===false&&$('resources').querySelector('[data-folder]'));
          if($('courseView').dataset.layout!=='list')throw Error('Root view mode did not survive reopening container');
          $('courseViewToggle').click();$('courseViewToggle').click();
          const rowCards=[...$('resources').querySelectorAll('.resource-card')],longTitle=rowCards[0].querySelector('.resource-card-title'),originalTitle=longTitle.textContent;longTitle.textContent='Una carpeta con un título suficientemente largo para ocupar varias líneas';const cardBottoms=rowCards.map(card=>card.offsetTop+card.offsetHeight);longTitle.textContent=originalTitle;if(Math.abs(cardBottoms[0]-cardBottoms[1])>1)throw Error('Cards in the same row have uneven bottoms: '+JSON.stringify(cardBottoms));
          $('searchToggle').click();$('ghost').value='Leccion';$('ghost').dispatchEvent(new Event('input'));
          await wait(()=>$('resources').querySelectorAll('[data-resource-key]').length===1);
          const resourceCard=$('resources').querySelector('.resource-card');
          if(!resourceCard?.querySelector('.card-type')||!resourceCard.querySelector('.card-size')||!resourceCard.querySelector('.favorite-mark')||!resourceCard.querySelector('.card-rating')||!resourceCard.querySelector('.card-author'))throw Error('File card does not match catalog metadata');
          if(!resourceCard?.querySelector('.resource-pin svg'))throw Error('Pinned explorer card has no pin');
          if(!resourceCard?.dataset.stateLabel||getComputedStyle(resourceCard,'::after').content==='none')throw Error('Explorer card lacks reading state gradient');
          resourceCard.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,clientX:260,clientY:innerHeight-24}));
          await wait(()=>$('popover').classList.contains('item-actions')&&!$('popover').hidden);
          const fileMenu=$('popover'),fileMenuRect=fileMenu.getBoundingClientRect(),fileDots=[...fileMenu.querySelectorAll('.item-actions-states button')].map(button=>button.getBoundingClientRect());
          const fileDotOffset=(fileDots[0].left+fileDots.at(-1).right-fileMenuRect.left-fileMenuRect.right)/2;
          if(Math.abs(fileDotOffset+3)>2)throw Error('File menu dots are off center by '+fileDotOffset+'px');
          if(!$('popover').querySelector('[data-item-action="storage"]')||$('popover').getBoundingClientRect().bottom>innerHeight-4)throw Error('Explorer context menu is missing or outside the screen');
          if(!$('popover').querySelector('[data-item-action="remove-recent"]'))throw Error('Recent file cannot be removed from Recents in explorer');
          $('popover').querySelector('[data-item-action="remove-recent"]').click();
          await wait(()=>window.balisco.state.resources.find(resource=>resource.id==='fixture_file')?.recent_hidden===1);
          if(window.balisco.state.view!=='course')throw Error('Scoped search left explorer');
          await wait(()=>$('details').hidden===false);
          if($('courseInspector').hidden!==true)throw Error('Original inspector was not reused');
          $('searchToggle').click();$('ghost').value='@confirmar:suprimir';$('ghost').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
          await wait(()=>window.balisco.state.confirmDelete===false);
          if((await original('bootstrap',{})).data.prefs.confirm_delete!=='false')throw Error('Delete confirmation command did not persist');
          $('searchToggle').click();$('ghost').value='@confirmar:suprimir';$('ghost').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
          await wait(()=>window.balisco.state.confirmDelete===true);
          const rowToDelete=$('resources').querySelector('[data-id="fixture_file"]');if(window.balisco.state.courseSelection?.id!=='fixture_file')rowToDelete.click();
          await wait(()=>window.balisco.state.courseSelection?.id==='fixture_file');
          document.body.dispatchEvent(new KeyboardEvent('keydown',{key:'Delete',bubbles:true}));
          await wait(()=>$('dialog').open);
          $('dialogBody').querySelector('button:last-child').click();
          if(!$('resources').querySelector('[data-id="fixture_file"]'))throw Error('Cancel did not preserve the resource');
          let deleteCalls=0,undoCalls=0;const previousCall=pywebview.api.call;
          pywebview.api.call=async(action,payload)=>{if(action==='container_trash'){deleteCalls++;return {ok:true,data:true};}if(action==='undo_delete'){undoCalls++;return {ok:true,data:{restored:true,name:'Leccion.pdf'}};}return previousCall(action,payload);};
          $('searchToggle').click();$('ghost').value='@confirmar:suprimir';$('ghost').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
          await wait(()=>window.balisco.state.confirmDelete===false);
          document.body.dispatchEvent(new KeyboardEvent('keydown',{key:'Delete',bubbles:true}));
          await wait(()=>deleteCalls===1&&!$('resources').querySelector('[data-id="fixture_file"]'));
          if($('dialog').open)throw Error('Disabled confirmation still opened a dialog');
          document.body.dispatchEvent(new KeyboardEvent('keydown',{key:'z',ctrlKey:true,bubbles:true}));
          await wait(()=>undoCalls===1&&$('resources').querySelector('[data-id="fixture_file"]'));
          return {ok:true,layout:$('courseView').dataset.layout,headerWidth:bar.width,explorerWidth:rect.width,contextWidth:menuRect.width,search:$('summary').textContent,inspector:$('details').hidden,zoomLevels:levels,zoomAnimated:animated};
        })().catch(e=>({ok:false,error:e.message,stack:e.stack}))"""
        done = threading.Event()
        window.evaluate_js(script, callback=lambda value: (RESULT.update(value), done.set()))
        if not done.wait(10):
            RESULT.update(ok=False, error='JavaScript timeout')
        if RESULT.get('ok'):
            window.resize(1800, 980)
            time.sleep(.2)
            large = window.evaluate_js("""(()=>{const $=id=>document.getElementById(id);$('courseViewToggle').click();const row=$('resources').querySelector('.resource'),name=row?.querySelector('.resource-name span'),style=name&&getComputedStyle(name);const result={columns:Number(getComputedStyle($('courseView')).getPropertyValue('--course-list-columns')),rowHeight:row?.getBoundingClientRect().height,nameWidth:name?.getBoundingClientRect().width,lineClamp:style?.webkitLineClamp};$('courseViewToggle').click();$('courseViewToggle').click();return result;})()""")
            RESULT['largeList'] = large
            if large['columns'] > 4 or large['rowHeight'] < 70 or large['nameWidth'] < 300 or large['lineClamp'] != '2':
                RESULT.update(ok=False,error='List does not reserve enough space for long names')
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
            window.resize(340, 660)
            time.sleep(.5)
            narrow = window.evaluate_js("""(()=>{const $=id=>document.getElementById(id),toggle=$('inspectorToggle').getBoundingClientRect();return {width:innerWidth,compact:$('inspector').classList.contains('is-compact'),catalog:$('courseView').getBoundingClientRect().width,toggleVisible:toggle.left>=0&&toggle.right<=innerWidth,controls:$('windowControls').getBoundingClientRect().right<=innerWidth};})()""")
            RESULT['narrowWindow'] = narrow
            if narrow['width'] < 600 and (not narrow['compact'] or narrow['catalog'] < narrow['width'] - 4 or not narrow['toggleVisible'] or not narrow['controls']):
                RESULT.update(ok=False, error='Narrow window did not release space for cards or show panel control')
            slide = window.evaluate_js("""(()=>{const panel=document.getElementById('inspector'),before=getComputedStyle(panel).transform;void panel.getBoundingClientRect().left;document.getElementById('inspectorToggle').click();const style=getComputedStyle(panel);void panel.getBoundingClientRect().left;return {reduced:matchMedia('(prefers-reduced-motion: reduce)').matches,before,after:style.transform,transition:style.transitionProperty,animations:panel.getAnimations().map(animation=>({name:animation.constructor.name,property:animation.transitionProperty})),sliding:panel.getAnimations().some(animation=>animation.transitionProperty==='transform')};})()""")
            RESULT['narrowSlide'] = slide
            if narrow['width'] < 600 and not slide['reduced'] and not slide['sliding']:
                RESULT.update(ok=False, error='Inspector does not animate its slide')
            time.sleep(.5)
            window.evaluate_js("document.querySelector('#resources [data-id=fixture_file]')?.click()")
            time.sleep(.35)
            overlay = window.evaluate_js("""(()=>{const $=id=>document.getElementById(id),panel=$('inspector').getBoundingClientRect(),catalog=$('courseView').getBoundingClientRect(),content=$('inspectorContent'),detail=$('details');return {width:innerWidth,panelWidth:panel.width,panelRight:panel.right,catalogWidth:catalog.width,detailWidth:detail.getBoundingClientRect().width,contentWidth:content.clientWidth};})()""")
            RESULT['narrowOverlay'] = overlay
            if overlay['width'] < 600 and (overlay['panelWidth'] < min(300, overlay['width'] - 24) - 2 or overlay['panelWidth'] > overlay['width'] - 20 or overlay['panelRight'] > overlay['width'] + 1 or overlay['catalogWidth'] < overlay['width'] - 4 or overlay['detailWidth'] > overlay['contentWidth']):
                RESULT.update(ok=False, error='Inspector overlay overflows narrow window')
            closing_slide = window.evaluate_js("""(()=>{document.getElementById('back').click();const panel=document.getElementById('inspector');document.getElementById('inspectorToggle').click();void panel.getBoundingClientRect().left;return {reduced:matchMedia('(prefers-reduced-motion: reduce)').matches,sliding:panel.getAnimations().some(animation=>animation.transitionProperty==='transform')};})()""")
            RESULT['narrowClosingSlide'] = closing_slide
            if narrow['width'] < 600 and not closing_slide['reduced'] and not closing_slide['sliding']:
                RESULT.update(ok=False, error='Inspector does not animate its close')
            time.sleep(.45)
            narrow_library = window.evaluate_js("""(()=>{const $=id=>document.getElementById(id),viewport=$('viewport').getBoundingClientRect(),cards=[...$('canvas').querySelectorAll('.card')].map(card=>card.getBoundingClientRect());return {width:innerWidth,viewport:viewport.width,compact:$('inspector').classList.contains('is-compact'),cardsFit:cards.length>0&&cards.every(card=>card.left>=viewport.left-1&&card.right<=viewport.right+1)};})()""")
            RESULT['narrowLibrary'] = narrow_library
            if narrow_library['width'] < 600 and (not narrow_library['compact'] or narrow_library['viewport'] < narrow_library['width'] - 4 or not narrow_library['cardsFit']):
                RESULT.update(ok=False, error='Library cards do not fit the narrow window')
            window.resize(1100, 750)
            time.sleep(.5)
            restored = window.evaluate_js("""(()=>({width:innerWidth,compact:document.getElementById('inspector').classList.contains('is-compact'),panelWidth:document.getElementById('inspector').getBoundingClientRect().width}))()""")
            RESULT['restoredWindow'] = restored
            if restored['width'] > 600 and (restored['compact'] or restored['panelWidth'] < 270):
                RESULT.update(ok=False, error='Inspector did not restore its wide-window preference')
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
                 ('fixture_file', 'Leccion.pdf', 'pdf', 'Curso/Unidad/Leccion.pdf', 'fixture'),
                 ('fixture_extra', 'Otro', 'pdf', 'Otro.pdf', 'fixture')],
            )
            db.execute("UPDATE items SET rating=5,es_favorito=1,estado_lectura='abandonado',fijado=1 WHERE drive_id='fixture_course'")
            db.execute("UPDATE items SET rating=2 WHERE drive_id='fixture_extra'")
            db.execute("UPDATE items SET ultimo_acceso=CURRENT_TIMESTAMP WHERE drive_id IN ('fixture_course','fixture_file','fixture_extra')")
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
