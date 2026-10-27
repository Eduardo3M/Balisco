import {icon} from './icons.js?v=22';
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const bytes=n=>n?`${(n/1024**(Math.min(3,Math.floor(Math.log(n)/Math.log(1024))))).toFixed(1)} ${['B','KB','MB','GB'][Math.min(3,Math.floor(Math.log(n)/Math.log(1024)))]}`:'—';
const states=['pendiente','interesado','leyendo','leido','abandonado'];
const defaultFilterStates=[...states];
let filterStates=[...defaultFilterStates];try{const saved=JSON.parse(localStorage.getItem('balisco.stateOrder')||'null');if(Array.isArray(saved)&&saved.length===defaultFilterStates.length&&defaultFilterStates.every(x=>saved.includes(x)))filterStates=saved;}catch{}
const defaultFilterTypes=['documento','contenedor','video','audio','imagen','otro'];
let filterTypes=[...defaultFilterTypes];try{const saved=JSON.parse(localStorage.getItem('balisco.typeOrder')||'null');if(Array.isArray(saved)&&saved.length===defaultFilterTypes.length){const migrated=saved.map(x=>x==='pdf'?'documento':x==='archivo'?'otro':x);if(defaultFilterTypes.every(x=>migrated.includes(x)))filterTypes=migrated;}}catch{}
const stateNames={pendiente:'Pendiente',interesado:'Interesado',leyendo:'Leyendo',leido:'Leído',abandonado:'Abandonado'};
const typeIcons={documento:'document',contenedor:'package',video:'video',audio:'audio',imagen:'image',otro:'other'};
const typeNames={documento:'Documentos',contenedor:'Contenedores',video:'Videos',audio:'Audio',imagen:'Imágenes',otro:'Otros archivos'};
const S={profileId:'',loading:true,items:[],tokens:[],selected:null,pinned:false,showOverlays:true,mode:'local',theme:'auto',zoom:195,wallpaper:'',containerWallpaper:'',wallpaperTarget:1,wallpaperPositions:{},wallpaperOpacity:24,wallpaperBlur:18,containerBackgroundOpacity:100,containerBackgroundBlur:18,confirmDelete:true,view:'grid',revision:0,selectionRevision:0,rows:new Map(),covers:new Map(),pending:new Map(),saving:Promise.resolve(),course:null,resources:[],coursePath:[],courseFolderIds:new Map(),courseQuery:'',courseSelection:null,courseSelectionRevision:0,courseSelectedKeys:new Set(),courseAnchorKey:null,courseViewMode:'details',courseZoom:{grid:0,list:1},courseCovers:new Map(),bulkIds:new Set(),similarIds:null,languages:['Español','Inglés'],showRecentTitles:false,importing:false,importingJob:null,importCancelling:false};
const profileStorageKey=key=>S.profileId?`${key}.perfil.${S.profileId}`:key;
const importJobs=new Map();
let importTab='file';
let importNotice='';
function setImportNotice(state){importNotice=state;$('imports').dataset.notice=state;}
let toastTimer,drawFrame,ghostTimer,ready=false,keyboardCardId=null;
async function api(action,payload={}){if(!window.pywebview?.api)throw Error('Abre Balisco con python main.py para conectar la biblioteca.');const r=await window.pywebview.api.call(action,payload);if(!r.ok)throw Error(r.error);return r.data;}
function notify(message,kind='info',persistent=false,cancelId=null){const el=$('toast');el.replaceChildren();if(cancelId){const text=document.createElement('span');text.className='toast-message';text.textContent=message;const cancel=document.createElement('button');cancel.className='toast-cancel';cancel.type='button';cancel.textContent='×';cancel.title='Cancelar importación';cancel.setAttribute('aria-label','Cancelar importación');cancel.disabled=S.importCancelling;cancel.onclick=()=>requestImportCancel(cancelId);el.append(text,cancel);}else el.textContent=message;el.dataset.kind=kind;el.hidden=false;el.classList.remove('toast-out','toast-in');void el.offsetWidth;el.classList.add('toast-in');clearTimeout(toastTimer);if(!persistent)toastTimer=setTimeout(()=>{el.classList.remove('toast-in');el.classList.add('toast-out');setTimeout(()=>{if(el.classList.contains('toast-out'))el.hidden=true;},260);},3000);}
function guard(fn){return (...args)=>{try{return Promise.resolve(fn(...args)).catch(report);}catch(e){report(e);}};}
function report(e){if(e.message==='Preferencia inválida')return;notify(e.message,'error');$('status').textContent='Revisa el aviso';}
function button(name,label,id){return `<button class="icon-button" id="${id}"${label?` title="${label}"`:''} aria-label="${label}">${icon(name)}</button>`;}
$('dock').innerHTML='<span id="summary" class="item-count" title="Elementos mostrados"></span><span class="divider"></span>'+button('tag','Metadatos y taxonomía','metadata')+button('heart','Mostrar solo favoritos','favorite')+button('status','Filtrar por estado','statusFilter')+button('star','Filtrar por calificación','rating')+button('filter','Filtrar por tipo','type')+button('sort','Ordenar biblioteca','sort')+'<span class="divider"></span>'+button('grid','Tamaño de la cuadrícula','zoom')+button('local','Modo de apertura: Local','mode')+button('dice','Buscar relacionados','dice')+button('similar','Buscar similares al elemento seleccionado','similar')+'<span class="divider"></span>'+button('refresh','Sincronizar biblioteca','sync')+button('download','Gestionar cargas','imports')+button('cloud','Mantenimiento de Google Drive','driveTools')+button('wallpaper','Fondo y tema','wallpaper')+button('details','Compactar panel de detalles','inspectorToggle')+button('winMin','Minimizar','winMin')+button('winMax','Maximizar','winMax')+button('winClose','Cerrar','winClose');
const windowControls=document.createElement('div');windowControls.id='windowControls';windowControls.setAttribute('aria-label','Panel lateral y controles de ventana');document.querySelector('.toolbar').append(windowControls);
function setToolbarPosition(position){const bottom=position==='bottom';document.body.classList.toggle('search-bottom',bottom);const searchBar=$('searchBar');if(bottom){document.body.append(searchBar);}else{document.querySelector('.toolbar').insertBefore(searchBar,$('dock'));}for(const id of ['inspectorToggle','winMin','winMax','winClose'])windowControls.append($(id));localStorage.setItem('balisco.toolbarPosition',bottom?'bottom':'top');$('popover').hidden=true;$('importPanel').hidden=true;hideTagSuggestions();popoverAnchor=null;requestAnimationFrame(scheduleDraw);}
$('similar').hidden=true;
$('winMin').onclick=guard(()=>api('window_minimize'));
let maximizedState=null;
function windowState(maximized){
 maximized=!!maximized;if(maximizedState===maximized)return;maximizedState=maximized;
 const button=$('winMax');button.innerHTML=icon(maximized?'winRestore':'winMax');button.title=maximized?'Restaurar':'Maximizar';button.setAttribute('aria-label',button.title);
 document.body.classList.toggle('window-maximized',maximized);
}
$('winMax').onclick=guard(async()=>{const r=await api('window_toggle_maximize');windowState(r?.maximized);});
$('winClose').onclick=guard(()=>window.balisco.close());
const toolbar=document.querySelector('.toolbar');
const interactive='button,input,textarea,select,a,[contenteditable],.chip,#popover,[role="slider"]';
toolbar.addEventListener('pointerdown', e => {
    if (e.button === 0 && !e.target.closest(interactive)) {
        e.preventDefault();
        api('window_drag', { rx: e.clientX / window.innerWidth, oy: e.clientY }).catch(report);
    }
});
toolbar.addEventListener('dblclick', e => {
    if (e.button === 0 && !e.target.closest(interactive)) {
        $('winMax').click();
    }
});
for(const edge of ['left','right','top','bottom','topleft','topright','bottomleft','bottomright']){
 const handle=document.createElement('div');handle.className='window-resize '+edge;handle.setAttribute('aria-hidden','true');
 handle.onpointerdown=e=>{if(e.button===0){e.preventDefault();api('window_resize',{edge}).catch(report);}};document.body.append(handle);
}
$('searchToggle').innerHTML=icon('search');
S.showOverlays=true;
$('dock').addEventListener('click',event=>{const control=event.target.closest('.icon-button');if(control)animateControl(control);},true);
function animateControl(control,cls='control-feedback'){
 if(!control)return;
 control.classList.remove(cls);
 void control.offsetWidth;
 control.classList.add(cls);
 setTimeout(()=>control.classList.remove(cls),cls==='favorite-toggle'?420:300);
}
function gridIcon(level){return `<svg viewBox="0 0 24 24" aria-hidden="true">${Array.from({length:4},(_,i)=>`<rect class="${i<level?'filled':''}" x="${3+(i%2)*11}" y="${3+Math.floor(i/2)*11}" width="7" height="7" rx="1"/>`).join('')}</svg>`;}
function updateGridIcon(columns,animate=false){const control=$('zoom');if(control.dataset.columns===String(columns))return;const {min,max}=zoomLevels(),level=columns-min+1;control.dataset.columns=String(columns);control.innerHTML=gridIcon(Math.max(1,Math.min(4,level)));control.title=`Cuadrícula: ${columns} columnas · nivel ${level} de ${max-min+1}`;control.setAttribute('aria-label',control.title);if(animate)animateControl(control,'grid-change');}
$('dice').innerHTML=icon('dice','dice-art')+icon('target','target-art');
for(const [id,name] of [['driveOpen','drive'],['localOpen','folder']])$(id).innerHTML=icon(name);
const inspectorToggle=$('inspectorToggle');
inspectorToggle.innerHTML=icon('sidebar');
inspectorToggle.setAttribute('aria-controls','details courseInspector inspectorEmpty');
const narrowInspector=matchMedia('(max-width:600px)');
let inspectorPreference=localStorage.getItem('balisco.inspectorCompact')==='true';
let narrowInspectorOpened=false;
function applyInspectorCompact(compact){
 const inspector=$('inspector');
 if(compact&&inspector.contains(document.activeElement))inspectorToggle.focus();
 inspector.classList.remove('selection-change');
 inspector.classList.toggle('is-compact',compact);
 inspectorToggle.classList.toggle('is-compact',compact);
 inspectorToggle.setAttribute('aria-expanded',String(!compact));
 const label=compact?'Expandir panel de detalles':'Compactar panel de detalles';
 inspectorToggle.setAttribute('aria-label',label);inspectorToggle.title=label;
 for(const id of ['inspectorEmpty','details','courseInspector']){$(id).inert=compact;$(id).setAttribute('aria-hidden',String(compact));}
 requestAnimationFrame(()=>{scheduleDraw();if(S.view==='course')updateCourseGridColumns();});
}
function setInspectorCompact(compact){
 if(narrowInspector.matches)narrowInspectorOpened=!compact;
 else{inspectorPreference=compact;localStorage.setItem('balisco.inspectorCompact',String(compact));}
 applyInspectorCompact(compact);
}
function syncResponsiveInspector(){applyInspectorCompact(narrowInspector.matches?!narrowInspectorOpened:inspectorPreference);}
inspectorToggle.onclick=()=>setInspectorCompact(!$('inspector').classList.contains('is-compact'));
syncResponsiveInspector();
narrowInspector.addEventListener('change',()=>{if(narrowInspector.matches)narrowInspectorOpened=false;syncResponsiveInspector();});
function animateInspectorSelection(){const inspector=$('inspector');if(inspector.classList.contains('is-compact'))return;inspector.classList.remove('selection-change');void inspector.offsetWidth;inspector.classList.add('selection-change');}
function art(item){const hue=[...item.drive_id].reduce((a,c)=>a+c.charCodeAt(0),0)%60+190,category=String(item.categoria_macro||'').toLocaleLowerCase(),labelOnly=category==='storage'||item.tipo_contenido==='contenedor';return `<div class="typography" style="--hue:${hue}"><div class="cover-category">${esc(item.categoria_macro||'Biblioteca')}</div>${labelOnly?'':`<div class="cover-title">${esc(item.titulo.replace(/\.(pdf|epub)$/i,''))}</div><div class="cover-rule"></div>`}</div>`;}
function setView(view){const previous=S.view;if(previous!=='course'&&view==='course'){S.libraryTokens=[...S.tokens];S.tokens=[];}else if(previous==='course'&&view!=='course'){S.tokens=[...(S.libraryTokens||[])];S.courseQuery='';}S.view=view;for(const [id,key] of [['viewport','grid'],['metadataView','metadata'],['courseView','course']])$(id).hidden=view!==key;$('viewTitle')&&($('viewTitle').textContent=view==='metadata'?'Metadatos':view==='course'?(S.course?.titulo||'Contenedor'):'Biblioteca');$('eyebrow')&&($('eyebrow').textContent=view==='course'?'RECURSOS':'TU ESPACIO DE CONOCIMIENTO');$('metadata').setAttribute('aria-pressed',String(view==='metadata'));if(view==='course'){$('details').hidden=!S.courseSelection?.detail?.item;$('courseInspector').hidden=true;$('inspectorEmpty').hidden=!!S.courseSelection;}else{$('courseInspector').hidden=true;if(view==='grid'){$('details').hidden=!S.selected;$('inspectorEmpty').hidden=!!S.selected;}}renderFilters();if(view==='grid')scheduleDraw();}
function updateSummary(){$('summary').textContent=String(S.items.length);$('summary').title='Elementos mostrados';}
function searchTokens(){const draft=$('ghost').hidden?'':$('ghost').value.trim();return draft&&!/^[+@-]/.test(draft)?[...S.tokens,draft]:S.tokens;}
let lastQueriedTokensKey='';
async function refresh(reset=false,reuseCards=false){if(S.view==='course'){renderFilters();renderResources();return;}const currentTokens=searchTokens(),currentKey=JSON.stringify(currentTokens);if(reuseCards&&currentKey===lastQueriedTokensKey&&!reset&&!S.similarIds)return;const rev=++S.revision;const result=await api('query',{tokens:currentTokens});if(rev!==S.revision)return;lastQueriedTokensKey=currentKey;if(S.similarIds){const byId=new Map(result.items.map(item=>[item.drive_id,item]));S.items=S.similarIds.map(id=>byId.get(id)).filter(Boolean);}else S.items=result.items;S.total=result.total;if(!reuseCards){S.rows.clear();$('canvas').replaceChildren();}if(reset)$('viewport').scrollTop=0;renderFilters();updateSummary();scheduleDraw();}
function scheduleDraw(){if(!drawFrame)drawFrame=requestAnimationFrame(()=>{drawFrame=0;draw();});}
function drawNow(){if(drawFrame){cancelAnimationFrame(drawFrame);drawFrame=0;}draw();requestAnimationFrame(draw);}
let suppressCardClick=false,marquee=null,marqueeFrame=0,selectionAnchorId=null;
const marqueeBox=document.createElement('div');marqueeBox.className='marquee-box';marqueeBox.hidden=true;$('viewport').append(marqueeBox);
$('viewport').addEventListener('pointerdown',e=>{if(e.button!==0||e.shiftKey||S.view!=='grid')return;const rect=$('viewport').getBoundingClientRect();marquee={x:e.clientX,y:e.clientY,rect,base:e.ctrlKey?new Set(S.bulkIds):new Set(),dragged:false,lastX:e.clientX,lastY:e.clientY,pointerId:e.pointerId};});
function paintMarquee(){if(!marquee)return;const v=$('viewport'),r=marquee.rect,levels=zoomLevels(),x1=Math.min(marquee.x,marquee.lastX)-r.left+v.scrollLeft,y1=Math.min(marquee.y,marquee.lastY)-r.top+v.scrollTop,x2=Math.max(marquee.x,marquee.lastX)-r.left+v.scrollLeft,y2=Math.max(marquee.y,marquee.lastY)-r.top+v.scrollTop;Object.assign(marqueeBox.style,{left:x1+'px',top:y1+'px',width:(x2-x1)+'px',height:(y2-y1)+'px'});marqueeBox.hidden=false;const width=levels.width,gap=levels.gap,cols=Math.max(levels.min,Math.min(levels.max,Math.floor((width+gap)/(S.zoom+gap)))),w=(width-gap*(cols-1))/cols,stride=Math.round(w*1.25)+captionHeightForColumns(cols,levels)+22;S.bulkIds=new Set(marquee.base);const first=Math.max(0,Math.floor((y1-16)/stride)),last=Math.min(Math.ceil(S.items.length/cols)-1,Math.floor((y2-16)/stride));for(let row=first;row<=last;row++)for(let col=0;col<cols;col++){const index=row*cols+col,item=S.items[index];if(!item)continue;const left=28+col*(w+gap),right=left+w,top=16+row*stride,bottom=top+stride-22;if(right>=x1&&left<=x2&&bottom>=y1&&top<=y2)S.bulkIds.add(item.drive_id);}updateBulkButton();scheduleDraw();}
$('viewport').addEventListener('pointermove',e=>{if(!marquee||e.pointerId!==marquee.pointerId)return;marquee.lastX=e.clientX;marquee.lastY=e.clientY;if(!marquee.dragged&&Math.hypot(e.clientX-marquee.x,e.clientY-marquee.y)>5){marquee.dragged=true;$('viewport').setPointerCapture(e.pointerId);}if(!marquee.dragged||marqueeFrame)return;marqueeFrame=requestAnimationFrame(()=>{marqueeFrame=0;paintMarquee();});});
$('viewport').addEventListener('pointerup',e=>{if(!marquee||e.pointerId!==marquee.pointerId)return;const dragged=marquee.dragged;if(dragged){marquee.lastX=e.clientX;marquee.lastY=e.clientY;if(marqueeFrame){cancelAnimationFrame(marqueeFrame);marqueeFrame=0;}paintMarquee();}marquee=null;marqueeBox.hidden=true;if(dragged){suppressCardClick=true;const last=[...S.bulkIds].at(-1);if(last){selectionAnchorId=last;guard(()=>select(last,true,true))();}else{S.selected=null;$('details').hidden=true;$('inspectorEmpty').hidden=false;}setTimeout(()=>{suppressCardClick=false;},0);}});
$('viewport').addEventListener('pointercancel',()=>{marquee=null;marqueeBox.hidden=true;if(marqueeFrame){cancelAnimationFrame(marqueeFrame);marqueeFrame=0;}});
let zoomAnchor=null;
function draw(){if(S.view!=='grid')return;const v=$('viewport'),levels=zoomLevels(),width=levels.width,gap=levels.gap,rawCols=Math.max(1,Math.floor((width+gap)/(S.zoom+gap))),cols=Math.max(levels.min,Math.min(levels.max,rawCols)),w=(width-gap*(cols-1))/cols,captionHeight=captionHeightForColumns(cols,levels),h=Math.round(w*1.25)+captionHeight,stride=h+22;updateGridIcon(cols);$('canvas').style.height=`${Math.ceil(S.items.length/cols)*stride}px`;if(zoomAnchor){v.scrollTop=Math.floor(zoomAnchor.index/cols)*stride+zoomAnchor.fraction*stride;zoomAnchor=null;}const start=Math.max(0,Math.floor(v.scrollTop/stride)-1)*cols,end=Math.min(S.items.length,(Math.ceil((v.scrollTop+v.clientHeight)/stride)+1)*cols);
 const needed=new Set();for(let i=start;i<end;i++){const item=S.items[i];needed.add(item.drive_id);let node=S.rows.get(item.drive_id);if(!node){node=card(item);S.rows.set(item.drive_id,node);$('canvas').append(node);}node.dataset.index=i;node.style.width=w+'px';node.style.height=h+'px';node.style.setProperty('--caption-height',captionHeight+'px');node.style.setProperty('--title-lines',captionHeight===110?'3':'2');node.style.left=((i%cols)*(w+gap))+'px';node.style.top=(Math.floor(i/cols)*stride)+'px';node.classList.toggle('selected',S.selected?.drive_id===item.drive_id);node.classList.toggle('bulk-selected',S.bulkIds.has(item.drive_id));}
 for(const [id,node] of S.rows)if(!needed.has(id)){node.remove();S.rows.delete(id);}
 const showLibraryHint=!S.items.length&&!searchTokens().length&&!S.similarIds;$('empty').hidden=!showLibraryHint;if(showLibraryHint)$('empty').innerHTML=S.loading?'<div class="library-loader" role="status" aria-label="Cargando biblioteca"><div class="loading-dots" aria-hidden="true"><span></span><span></span><span></span></div></div>':'<h2>Tu biblioteca empieza aquí</h2><p>Sincroniza tu Biblioteca de Google Drive para empezar.</p>';
}
async function focusCardIndex(index,updateSelection=true){
 const item=S.items[index];if(!item||S.view!=='grid')return;
 const v=$('viewport'),levels=zoomLevels(),width=levels.width,gap=levels.gap,cols=Math.max(levels.min,Math.min(levels.max,Math.floor((width+gap)/(S.zoom+gap)))),cardWidth=(width-gap*(cols-1))/cols,cardHeight=Math.round(cardWidth*1.25)+captionHeightForColumns(cols,levels),stride=cardHeight+22,top=16+Math.floor(index/cols)*stride,bottom=top+cardHeight;
 if(top<v.scrollTop+16)v.scrollTop=Math.max(0,top-16);
 else if(bottom>v.scrollTop+v.clientHeight-24)v.scrollTop=bottom-v.clientHeight+24;
 draw();S.rows.get(item.drive_id)?.focus({preventScroll:true});keyboardCardId=item.drive_id;
 if(updateSelection)await select(item.drive_id);
}
function card(item){const el=document.createElement('article'),authors=authorNames(item.autor),category=String(item.categoria_macro||'').toLocaleLowerCase();el.className='card'+(category==='storage'?' storage-card':'')+(item.tipo_contenido==='contenedor'?' container-card':'');el.tabIndex=0;el.dataset.state=item.estado_lectura||'pendiente';el.setAttribute('aria-label',item.titulo+(item.es_favorito?', favorito':''));el.ondragstart=e=>e.preventDefault();const type=({contenedor:'CONTENEDOR',documento:'DOCUMENTO',video:'VIDEO',audio:'AUDIO',imagen:'IMAGEN',otro:'ARCHIVO'})[item.tipo_contenido]||item.tipo_contenido?.toUpperCase()||item.tipo.toUpperCase();el.innerHTML=`<div class="cover">${art(item)}${item.fijado?`<span class="card-pin" title="Fijado">${icon('pin')}</span>`:''}</div><div class="card-info"><div class="card-title">${esc(item.titulo)}</div><div class="card-meta"><span class="card-type" title="${type}" aria-label="${type}">${type[0]}</span><span class="card-size">${esc(bytes(item.tamano_bytes))}</span>${item.es_favorito?`<span class="favorite-mark" title="Favorito">${icon('heart')}</span>`:''}${item.rating?`<span class="card-rating">${icon('star')} ${item.rating}</span>`:''}${authors.length?`<span class="card-author" title="${esc(authors.join(', '))}">· ${esc(authors[0])}${authors.length>1?' +'+(authors.length-1):''}</span>`:''}</div>${item.coincidencia_interna?.length?`<div class="internal-match" title="Coincidencia dentro del contenedor">Dentro: ${esc(item.coincidencia_interna.join(', '))}</div>`:''}</div>`;
 el.onfocus=()=>{keyboardCardId=item.drive_id;};
 el.onclick=guard(e=>{if(suppressCardClick){suppressCardClick=false;return;}const closedMenu=closeRepeatedItemActions(el);if(closedMenu){selectionAnchorId=item.drive_id;if(!S.bulkIds.has(item.drive_id))S.bulkIds=new Set([item.drive_id]);return select(item.drive_id,true,true);}if(e.shiftKey)return selectGridRange(item.drive_id,e.ctrlKey);selectionAnchorId=item.drive_id;if(e.ctrlKey)return toggleBulkSelection(item.drive_id);if(S.selected?.drive_id===item.drive_id){S.selected=null;S.bulkIds.clear();$('details').hidden=true;$('inspectorEmpty').hidden=false;updateBulkButton();scheduleDraw();return;}return select(item.drive_id);});el.ondblclick=guard(e=>e.ctrlKey||e.shiftKey?undefined:openItem(item));el.onkeydown=guard(e=>{if(e.target!==el)return;if(e.key==='Enter'){e.preventDefault();return e.ctrlKey?toggleBulkSelection(item.drive_id):openItem(item);}if(e.key===' '){e.preventDefault();selectionAnchorId=item.drive_id;return e.ctrlKey?toggleBulkSelection(item.drive_id):e.shiftKey?selectGridRange(item.drive_id):select(item.drive_id);}if(e.key==='F2'){e.preventDefault();el.querySelector('.state-button')?.focus();}});
 el.oncontextmenu=guard(async e=>{e.preventDefault();if(closeRepeatedItemActions(el))return;const point={x:e.clientX,y:e.clientY};if(!S.bulkIds.has(item.drive_id)){S.bulkIds=new Set([item.drive_id]);await select(item.drive_id,true,true);}await openItemActions(el,[...S.bulkIds],false,point);});loadCover(item.drive_id).then(src=>{if(src){coverCache.set(item.drive_id,src);if(el.isConnected){const img=new Image();img.src=src;img.decoding='async';img.alt='';el.querySelector('.cover').prepend(img);el.querySelector('.typography').hidden=true;}}}).catch(()=>{});return el;}
let coverQueue=[],coverActive=0;
const coverCache=new Map();
function getCachedCover(id){if(!id)return null;if(coverCache.has(id))return coverCache.get(id);const cardImg=S.rows.get(id)?.querySelector('.cover img');if(cardImg?.src&&!cardImg.src.endsWith('undefined')){coverCache.set(id,cardImg.src);return cardImg.src;}return null;}
function loadCover(id){if(coverCache.has(id))return Promise.resolve(coverCache.get(id));if(S.covers.has(id))return S.covers.get(id);const promise=new Promise((resolve,reject)=>{coverQueue.push({id,resolve:src=>{if(src)coverCache.set(id,src);resolve(src);},reject});pumpCovers();});S.covers.set(id,promise);if(S.covers.size>250)S.covers.delete(S.covers.keys().next().value);return promise;}
function pumpCovers(){while(coverActive<3&&coverQueue.length){const job=coverQueue.shift();coverActive++;api('cover',{id:job.id}).then(job.resolve,job.reject).finally(()=>{coverActive--;pumpCovers();});}}
function renderFilters(){
 const focused=document.activeElement?.closest?.('#filters [data-index]');
 const focusedIndex=focused?Number(focused.dataset.index):-1;
 $('filters').innerHTML=S.tokens.map((t,i)=>`<button class="chip ${t.startsWith('+')?'include':t.startsWith('-')?'exclude':t.startsWith('@')?'gold':''}" data-index="${i}" title="Quitar filtro ${esc(t)} · Retroceso" aria-keyshortcuts="Backspace">${esc(t)}${icon('close')}</button>`).join('');
 if(focusedIndex>=0){const next=$('filters').querySelector(`[data-index="${Math.min(focusedIndex,S.tokens.length-1)}"]`);if(next)next.focus({preventScroll:true});else $('searchToggle').focus({preventScroll:true});}
 const favorite=S.tokens.includes('@favoritos');
 const state=[...S.tokens].reverse().find(t=>filterStates.includes(t.slice(1)))?.slice(1);
 const rating=[...S.tokens].reverse().find(t=>/^@rating:[1-5]$/.test(t));
 const type=[...S.tokens].reverse().find(t=>['documento','contenedor','video','audio','imagen','otro'].includes(t.slice(6))&&t.startsWith('@tipo:'))?.slice(6);
 const labels={favorite:favorite?'Mostrar todos los elementos':'Mostrar solo favoritos',statusFilter:state?'Estado: '+stateNames[state]:'Todos los estados',rating:rating?'Calificación: '+rating.slice(8)+' estrellas':'Filtrar por calificación',type:type?'Tipo: '+typeNames[type]:'Filtrar por tipo'};
 for(const [id,active] of [['favorite',favorite],['statusFilter',!!state],['rating',!!rating],['type',!!type]]){
  const button=$(id);button.setAttribute('aria-pressed',String(active));button.title=labels[id];button.setAttribute('aria-label',labels[id]);
 }
 const previousFavorite=$('favorite').dataset.favorite;
 $('favorite').dataset.favorite=String(favorite);
 if(previousFavorite&&previousFavorite!==String(favorite))animateControl($('favorite'),'favorite-toggle');
 const previousState=$('statusFilter').dataset.state;
 $('statusFilter').innerHTML=`<span class="state-indicator ${state||'all'}"></span>`;
 $('statusFilter').dataset.state=state||'all';
 if(previousState&&previousState!==$('statusFilter').dataset.state)animateControl($('statusFilter'),'state-filter-change');
 const fill=rating?[0,15,33,50,75,100][Number(rating.slice(8))]:0;
 if(!$('rating').querySelector('.rating-indicator'))$('rating').innerHTML=`<span class="rating-indicator">${icon('star')}<span class="rating-fill">${icon('star')}</span></span>`;
 const previousRating=$('rating').dataset.rating;
 $('rating').dataset.rating=String(fill);
 $('rating').querySelector('.rating-fill').style.width=fill+'%';
 if(previousRating&&previousRating!==String(fill))animateControl($('rating'),'rating-change');
 $('type').innerHTML=icon(type?typeIcons[type]:'filter');
}
async function toggleFacet(prefix,token){
 const previous=[...S.tokens],current=S.tokens.find(value=>value.startsWith(prefix));
 S.tokens=S.tokens.filter(value=>!value.startsWith(prefix));
 if(current!==token)S.tokens.push(token);
 try{await flush();if(S.view!=='course')setView('grid');await refresh(true);}catch(e){S.tokens=previous;renderFilters();throw e;}
}
async function toggleFacetState(state){
 const previous=[...S.tokens],current=filterStates.find(value=>S.tokens.includes('@'+value));
 S.tokens=S.tokens.filter(value=>!filterStates.some(option=>value==='@'+option));
 if(current!==state)S.tokens.push('@'+state);
 try{await flush();if(S.view!=='course')setView('grid');await refresh(true);}catch(e){S.tokens=previous;renderFilters();throw e;}
}
async function addToken(token){token=token.trim();if(!token||S.tokens.includes(token))return;if(token.startsWith('+')||token.startsWith('-'))recordRecentTag(token);const previous=[...S.tokens];S.tokens.push(token);try{await flush();if(S.view!=='course')setView('grid');await refresh(true);}catch(e){S.tokens=previous;renderFilters();throw e;}}
let swiping=false,swipeTokens=new Set();
$('filters').onpointerdown=e=>{const el=e.target.closest('[data-index]');if(!el||e.button!==0)return;swiping=true;swipeTokens.add(S.tokens[+el.dataset.index]);el.style.opacity='.2';e.preventDefault();};
document.addEventListener('pointermove',e=>{if(!swiping)return;const el=document.elementFromPoint(e.clientX,e.clientY)?.closest('#filters [data-index]');if(el){swipeTokens.add(S.tokens[+el.dataset.index]);el.style.opacity='.2';}});
document.addEventListener('pointerup',guard(async()=>{if(!swiping)return;swiping=false;S.tokens=S.tokens.filter(t=>!swipeTokens.has(t));swipeTokens.clear();await refresh(true);}));
$('filters').onclick=guard(async e=>{if(e.detail!==0)return;const el=e.target.closest('[data-index]');if(el){S.tokens.splice(+el.dataset.index,1);await refresh(true);}else{ghostShow();}});
function focusFilter(index){const chip=$('filters').querySelector(`[data-index="${index}"]`);if(chip){chip.focus({preventScroll:true});chip.scrollIntoView({block:'nearest',inline:'nearest'});}}
$('filters').onkeydown=guard(async e=>{const chip=e.target.closest('[data-index]');if(!chip)return;const index=Number(chip.dataset.index);if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();focusFilter((index+(e.key==='ArrowLeft'?-1:1)+S.tokens.length)%S.tokens.length);return;}if(e.key==='Delete'){e.preventDefault();e.stopPropagation();return;}if(e.key==='Backspace'){e.preventDefault();S.tokens.splice(index,1);await refresh(true);if(S.tokens.length)focusFilter(Math.min(index,S.tokens.length-1));else $('searchToggle').focus({preventScroll:true});}});
function getSearchHistory(){
  try{
    const raw=JSON.parse(localStorage.getItem(profileStorageKey('balisco.searchHistory'))||'[]');
    if(!Array.isArray(raw))return [];
    return raw.map(item=>{
      if(typeof item==='string'){
        const low=item.toLowerCase();
        let type='title';
        if(item.startsWith('+')||item.startsWith('-'))type='tag';
        else if(low.startsWith('@autor:')||low.startsWith('autor:'))type='author';
        else if(item.startsWith('@')||item.startsWith('.')||item.startsWith('/'))type='command';
        return {term:item,type,time:Date.now()};
      }
      if(!item||!item.term)return null;
      if(!item.type){
        const low=String(item.term).toLowerCase();
        let type='title';
        if(item.term.startsWith('+')||item.term.startsWith('-'))type='tag';
        else if(low.startsWith('@autor:')||low.startsWith('autor:'))type='author';
        else if(item.term.startsWith('@')||item.term.startsWith('.')||item.term.startsWith('/'))type='command';
        item.type=type;
      }
      return item;
    }).filter(Boolean);
  }catch{return [];}
}

function recordSearchHistory(term){
  const raw=String(term||'').trim();
  if(!raw||raw.length<2)return;
  const low=raw.toLowerCase();
  let type='title';
  if(raw.startsWith('+')||raw.startsWith('-'))type='tag';
  else if(low.startsWith('@autor:')||low.startsWith('@autores:')||low.startsWith('autor:'))type='author';
  else if(raw.startsWith('@')||raw.startsWith('.')||raw.startsWith('/')||low==='.help')type='command';
  try{
    const list=getSearchHistory().filter(item=>item&&item.term&&item.term.toLowerCase()!==low);
    list.unshift({term:raw,type,time:Date.now()});
    localStorage.setItem(profileStorageKey('balisco.searchHistory'),JSON.stringify(list.slice(0,50)));
  }catch{}
}

function getRecentStates(){
  try{return JSON.parse(localStorage.getItem(profileStorageKey('balisco.recentStates'))||'[]');}catch{return [];}
}
function recordRecentState(state){
  const clean=String(state||'').trim().toLowerCase();
  if(!clean)return;
  try{
    const list=getRecentStates().filter(s=>s!==clean);
    list.unshift(clean);
    localStorage.setItem(profileStorageKey('balisco.recentStates'),JSON.stringify(list.slice(0,10)));
  }catch{}
}

function getRecentAuthors(){
  try{return JSON.parse(localStorage.getItem(profileStorageKey('balisco.recentAuthors'))||'[]');}catch{return [];}
}
function recordRecentAuthor(name){
  const clean=String(name||'').trim();
  if(!clean)return;
  try{
    const list=getRecentAuthors().filter(a=>a.toLowerCase()!==clean.toLowerCase());
    list.unshift(clean);
    localStorage.setItem(profileStorageKey('balisco.recentAuthors'),JSON.stringify(list.slice(0,50)));
  }catch{}
}

function getRecentTagMap(){try{return JSON.parse(localStorage.getItem(profileStorageKey('balisco.recentTags'))||'{}');}catch{return {};}}
function recordRecentTag(tag){const clean=String(tag||'').replace(/^[+-]/,'').trim().toLowerCase();if(!clean)return;try{const map=getRecentTagMap();map[clean]=new Date().toISOString();const sorted=Object.entries(map).sort((a,b)=>b[1].localeCompare(a[1])).slice(0,150);localStorage.setItem(profileStorageKey('balisco.recentTags'),JSON.stringify(Object.fromEntries(sorted)));}catch{}}
let tagCatalog=null,tagCatalogAt=0,tagCatalogPromise=null,authorCatalog=null,authorCatalogPromise=null,tagMatches=[],tagSuggestionIndex=-1,tagSuggestionRevision=0;
const foldText=value=>String(value??'').normalize('NFD').replace(/\p{M}/gu,'').replace(/[\s_-]+/g,' ').trim().toLocaleLowerCase();
async function loadTagCatalog(force=false){if(!force&&tagCatalog&&Date.now()-tagCatalogAt<30000)return tagCatalog;if(!tagCatalogPromise)tagCatalogPromise=api('tag_suggestions');try{tagCatalog=await tagCatalogPromise;tagCatalogAt=Date.now();return tagCatalog;}finally{tagCatalogPromise=null;}}
async function loadAuthorCatalog(){if(authorCatalog)return authorCatalog;if(!authorCatalogPromise)authorCatalogPromise=api('authors');try{authorCatalog=await authorCatalogPromise;return authorCatalog;}finally{authorCatalogPromise=null;}}
function hideTagSuggestions(){tagSuggestionRevision++;tagMatches=[];tagSuggestionIndex=-1;$('tagSuggestions').hidden=true;$('ghost').setAttribute('aria-expanded','false');$('ghost').removeAttribute('aria-activedescendant');}

function positionTagSuggestions(){
  const input=$('ghost'),menu=$('tagSuggestions');
  if(!input||input.hidden||menu.hidden)return;
  const rect=input.getBoundingClientRect();
  const bottom=document.body.classList.contains('search-bottom');
  const variant=menu.dataset.variant||'commands';
  let minW=350,maxW=540;
  if(variant==='tags'){
    minW=Math.max(180,Math.round(rect.width));
    maxW=320;
  }else if(variant==='authors'){
    minW=Math.max(260,Math.round(rect.width));
    maxW=420;
  }
  menu.style.minWidth=`min(${minW}px, calc(100vw - 24px))`;
  menu.style.width='max-content';
  menu.style.maxWidth=`min(${maxW}px, calc(100vw - 24px))`;
  const menuWidth=Math.min(maxW,Math.max(minW,menu.offsetWidth||minW));
  let left=rect.left;
  if(left+menuWidth>window.innerWidth-12){
    left=Math.max(12,window.innerWidth-menuWidth-12);
  }
  menu.style.left=Math.round(left)+'px';
  menu.style.maxHeight='290px';
  if(bottom){
    menu.style.bottom=Math.max(8,Math.round(window.innerHeight-rect.top+7))+'px';
    menu.style.top='auto';
  }else{
    const height=Math.min(menu.scrollHeight||290,290);
    let top=rect.bottom+7;
    if(top+height>window.innerHeight-8)top=Math.max(8,rect.top-height-7);
    menu.style.top=Math.round(top)+'px';
    menu.style.bottom='auto';
  }
}

const COMMAND_SUGGESTIONS = [
  {cmd: '@estado:', desc: 'Filtrar por estado (leido, leyendo, pendiente…)', keywords: ['estado', 'estados', 'leyendo', 'leido', 'pendiente', 'status']},
  {cmd: '@autor:', desc: 'Filtrar por autor de la biblioteca', keywords: ['autor', 'autores', 'author', 'creador', 'escritor']},
  {cmd: '@idioma:', desc: 'Filtrar libros por idioma (español, inglés…)', keywords: ['idioma', 'idiomas', 'lenguaje', 'lang', 'language']},
  {cmd: '@orden:', desc: 'Ordenar por recientes, peso, alfabético…', keywords: ['orden', 'ordenar', 'sort', 'peso', 'recientes', 'alfabetico']},
  {cmd: '@formato:', desc: 'Filtrar por formato (pdf, epub, cbz…)', keywords: ['formato', 'fmt', 'extension', 'pdf', 'epub']},
  {cmd: '@rating:', desc: 'Filtrar por estrellas (1 a 5)', keywords: ['rating', 'calificacion', 'estrellas', 'stars']},
  {cmd: '@idiomas', desc: 'Administrar idiomas disponibles', keywords: ['idiomas', 'idioma', 'languages', 'lang']},
  {cmd: '@barra', desc: 'Mover la barra de búsqueda arriba / abajo', keywords: ['barra', 'toolbar', 'mover', 'abajo', 'arriba']},
  {cmd: '@recientes:titulos', desc: 'Activar/desactivar títulos en recientes', keywords: ['titulos', 'recientes', 'historial', 'mostrar titulos']},
  {cmd: '@favoritos', desc: 'Mostrar solo libros favoritos', keywords: ['favoritos', 'fav', 'destacados']},
  {cmd: '@recientes', desc: 'Mostrar libros abiertos recientemente', keywords: ['recientes', 'historial', 'ultimos']},
  {cmd: '@ocultos', desc: 'Mostrar libros y archivos ocultos', keywords: ['ocultos', 'oculto', 'hidden']},
  {cmd: '@peso:', desc: 'Filtrar por peso (ej. >50mb, <1gb)', keywords: ['peso', 'tamano', 'mb', 'gb']},
  {cmd: '@con:notas', desc: 'Libros con notas o apuntes', keywords: ['notas', 'apuntes']},
  {cmd: '@sin:portada', desc: 'Libros sin portada personalizada', keywords: ['sin portada', 'portada', 'cover']},
  {cmd: '@confirmar:suprimir', desc: 'Activar/desactivar confirmación de Suprimir', keywords: ['confirmar', 'suprimir', 'borrar', 'eliminar']},
  {cmd: '.help', desc: 'Abrir ventana de ayuda y comandos', keywords: ['help', 'ayuda', 'comandos', '?']}
];

const READING_STATES = [
  {id: 'pendiente', label: 'Pendiente', desc: 'Por leer o en espera'},
  {id: 'interesado', label: 'Interesado', desc: 'En lista de deseos / para revisar'},
  {id: 'leyendo', label: 'Leyendo', desc: 'En progreso de lectura'},
  {id: 'leido', label: 'Leído', desc: 'Lectura completada'},
  {id: 'abandonado', label: 'Abandonado', desc: 'Lectura descartada'}
];

const SORT_OPTIONS_MENU = [
  {key: 'recientes', label: 'Recientes', desc: 'Por acceso más reciente'},
  {key: 'peso', label: 'Peso / Tamaño', desc: 'Mayor tamaño a menor'},
  {key: 'alfabetico', label: 'Alfabético', desc: 'De la A a la Z por título'},
  {key: 'antiguos', label: 'Antiguos', desc: 'Por fecha más antigua'},
  {key: 'abiertos', label: 'Abiertos / Lectura', desc: 'Por estado de lectura'}
];

const COMMON_FORMATS = [
  {fmt: 'pdf', desc: 'Documento PDF'},
  {fmt: 'epub', desc: 'Libro electrónico EPUB'},
  {fmt: 'cbz', desc: 'Cómic digital CBZ'},
  {fmt: 'cbr', desc: 'Cómic digital CBR'},
  {fmt: 'mobi', desc: 'Libro Kindle MOBI'},
  {fmt: 'azw3', desc: 'Libro Kindle AZW3'},
  {fmt: 'mp4', desc: 'Video MP4'},
  {fmt: 'mp3', desc: 'Audio MP3'},
  {fmt: 'zip', desc: 'Archivo comprimido ZIP'},
  {fmt: 'rar', desc: 'Archivo comprimido RAR'}
];

function getCommandMatches(text){
  const clean=String(text||'').trim().toLowerCase();
  if(!clean)return [];
  if(!clean.startsWith('@')&&!clean.startsWith('.')&&!clean.startsWith('/')){
    if(clean==='help')return COMMAND_SUGGESTIONS.filter(item=>item.cmd==='.help');
    return [];
  }
  const query=clean.replace(/^[@.\/]/,'');
  return COMMAND_SUGGESTIONS.filter(item=>{
    const cmdNorm=item.cmd.toLowerCase();
    const cmdWithoutPrefix=cmdNorm.replace(/^[@.]/,'');
    if(cmdNorm.startsWith(clean))return true;
    if(!query)return true;
    return cmdWithoutPrefix.includes(query)||item.desc.toLowerCase().includes(query)||item.keywords.some(k=>k.includes(query));
  });
}

async function updateTagSuggestions(){
  const raw=$('ghost').value;
  const text=raw.trim();
  const empty=!text;
  const low=text.toLowerCase();

  const isTag=text.startsWith('+')||text.startsWith('-');
  const isStateSec=low.startsWith('@estado:')||low.startsWith('@estados:')||low==='@estado';
  const isAuthorSec=low.startsWith('@autor:')||low.startsWith('@autores:')||low==='@autor';
  const isLangSec=low.startsWith('@idioma:')||low.startsWith('@lang:')||low==='@idioma';
  const isSortSec=low.startsWith('@orden:')||low.startsWith('@sort:')||low==='@orden';
  const isFormatSec=low.startsWith('@formato:')||low.startsWith('@fmt:')||low==='@formato';
  const isRatingSec=low.startsWith('@rating:')||low==='@rating';
  const isGeneralCmd=text.startsWith('@')||text.startsWith('.')||text.startsWith('/')||low==='.help'||low==='help';

  if($('ghost').hidden||(!empty&&!isTag&&!isStateSec&&!isAuthorSec&&!isLangSec&&!isSortSec&&!isFormatSec&&!isRatingSec&&!isGeneralCmd)){
    hideTagSuggestions();
    return;
  }

  const revision=++tagSuggestionRevision,menu=$('tagSuggestions');

  if(empty){
    const history=getSearchHistory();
    const recents=S.showRecentTitles?history:history.filter(h=>h&&h.type&&h.type!=='title');
    if(recents.length){
      menu.dataset.variant='commands';
      menu.hidden=false;$('ghost').setAttribute('aria-expanded','true');
      tagMatches=recents.slice(0,10).map(h=>({
        value:h.term,
        label:h.term,
        desc:h.type==='tag'?'Filtro por etiqueta':h.type==='author'?'Filtro por autor':h.type==='command'?'Comando del sistema':'Búsqueda de título',
        meta:h.type==='tag'?'etiqueta':h.type==='author'?'autor':h.type==='command'?'comando':'título',
        type:h.type
      }));
      tagSuggestionIndex=-1;$('ghost').removeAttribute('aria-activedescendant');
      const heading=S.showRecentTitles?'BÚSQUEDAS RECIENTES':'RECIENTES (ETIQUETAS Y COMANDOS)';
      menu.innerHTML=`<div class="suggestion-heading">${heading}</div>`+tagMatches.map((item,index)=>`
        <button type="button" id="tagSuggestion${index}" data-suggestion="${index}" role="option" aria-selected="false">
          <span class="suggestion-main">
            <span class="suggestion-cmd">${esc(item.label)}</span>
            <span class="suggestion-desc">${esc(item.desc)}</span>
          </span>
          <small class="suggestion-badge">${esc(item.meta)}</small>
        </button>
      `).join('');
      positionTagSuggestions();
      return;
    }

    let catalog=null;
    try{catalog=await loadTagCatalog();}catch{}
    if(catalog&&catalog.length){
      const recentMap=getRecentTagMap();
      const getLocalRecency=item=>recentMap[String(item.tag||'').toLowerCase()]||'';
      tagMatches=catalog.slice().sort((a,b)=>{
        const localA=getLocalRecency(a),localB=getLocalRecency(b);
        if(localA!==localB){
          if(!localA)return 1;
          if(!localB)return -1;
          return localB.localeCompare(localA);
        }
        return (b.total||0)-(a.total||0);
      }).slice(0,8).map(item=>({
        value:'+'+item.tag,
        label:'+'+item.tag,
        desc:`${item.total} ${item.total===1?'libro':'libros'}`,
        meta:'etiqueta',
        type:'tag'
      }));
      if(tagMatches.length){
        menu.dataset.variant='tags';
        menu.hidden=false;$('ghost').setAttribute('aria-expanded','true');
        tagSuggestionIndex=-1;$('ghost').removeAttribute('aria-activedescendant');
        menu.innerHTML='<div class="suggestion-heading">ETIQUETAS RECIENTES</div>'+tagMatches.map((item,index)=>`
          <button type="button" id="tagSuggestion${index}" data-suggestion="${index}" role="option" aria-selected="false">
            <span class="suggestion-cmd">${esc(item.label)}</span>
            <small class="suggestion-count">${esc(item.desc)}</small>
          </button>
        `).join('');
        positionTagSuggestions();
        return;
      }
    }

    menu.hidden=false;$('ghost').setAttribute('aria-expanded','true');
    tagMatches=COMMAND_SUGGESTIONS.slice(0,8).map(c=>({
      value:c.cmd,
      label:c.cmd,
      desc:c.desc,
      meta:'comando',
      type:'command'
    }));
    tagSuggestionIndex=-1;$('ghost').removeAttribute('aria-activedescendant');
    menu.innerHTML='<div class="suggestion-heading">COMANDOS Y SECCIONES</div>'+tagMatches.map((item,index)=>`
      <button type="button" id="tagSuggestion${index}" data-suggestion="${index}" role="option" aria-selected="false">
        <span class="suggestion-main">
          <span class="suggestion-cmd">${esc(item.label)}</span>
          <span class="suggestion-desc">${esc(item.desc)}</span>
        </span>
        <small class="suggestion-badge">${esc(item.meta)}</small>
      </button>
    `).join('');
    positionTagSuggestions();
    return;
  }

  if(isStateSec){
    menu.dataset.variant='commands';
    const after=text.includes(':')?text.slice(text.indexOf(':')+1).trim():'';
    const needle=foldText(after);
    const recentStates=getRecentStates();
    const sorted=[...READING_STATES].sort((a,b)=>{
      const idxA=recentStates.indexOf(a.id);
      const idxB=recentStates.indexOf(b.id);
      if(idxA!==-1&&idxB!==-1)return idxA-idxB;
      if(idxA!==-1)return -1;
      if(idxB!==-1)return 1;
      return 0;
    });
    const matches=sorted.filter(s=>!needle||foldText(s.id).includes(needle)||foldText(s.label).includes(needle)||foldText(s.desc).includes(needle));
    menu.hidden=false;$('ghost').setAttribute('aria-expanded','true');
    tagMatches=matches.map(s=>({
      value:`@estado:${s.id}`,
      label:`@estado:${s.id}`,
      desc:s.desc,
      meta:'estado',
      type:'state',
      stateId:s.id
    }));
    tagSuggestionIndex=-1;$('ghost').removeAttribute('aria-activedescendant');
    if(tagMatches.length){
      menu.innerHTML='<div class="suggestion-heading">ESTADOS DE LECTURA</div>'+tagMatches.map((item,index)=>`
        <button type="button" id="tagSuggestion${index}" data-suggestion="${index}" role="option" aria-selected="false">
          <span class="suggestion-main">
            <span class="suggestion-cmd">${esc(item.label)}</span>
            <span class="suggestion-desc">${esc(item.desc)}</span>
          </span>
          <small class="suggestion-badge">${esc(item.meta)}</small>
        </button>
      `).join('');
    }else{
      menu.innerHTML=`<div class="suggestion-empty">Sin estados coincidentes con «${esc(after)}»</div>`;
    }
    positionTagSuggestions();
    return;
  }

  if(isAuthorSec){
    menu.dataset.variant='authors';
    const after=text.includes(':')?text.slice(text.indexOf(':')+1).trim():'';
    const needle=foldText(after);
    if(!authorCatalog){
      menu.hidden=false;$('ghost').setAttribute('aria-expanded','true');
      menu.innerHTML='<div class="suggestion-loading">Cargando autores de la biblioteca…</div>';
      positionTagSuggestions();
    }
    let catalog;
    try{catalog=await loadAuthorCatalog();}
    catch(err){
      if(revision===tagSuggestionRevision){
        menu.innerHTML='<div class="suggestion-empty">No se pudieron cargar los autores</div>';
        positionTagSuggestions();
      }
      throw err;
    }
    if(revision!==tagSuggestionRevision||$('ghost').hidden||$('ghost').value.trim()!==text)return;
    const recentAuthors=getRecentAuthors();
    const matches=(catalog||[]).filter(a=>!needle||foldText(a.author).includes(needle)).sort((a,b)=>{
      const idxA=recentAuthors.findIndex(x=>x.toLowerCase()===a.author.toLowerCase());
      const idxB=recentAuthors.findIndex(x=>x.toLowerCase()===b.author.toLowerCase());
      if(idxA!==-1&&idxB!==-1&&idxA!==idxB)return idxA-idxB;
      if(idxA!==-1&&idxB===-1)return -1;
      if(idxA===-1&&idxB!==-1)return 1;
      if(needle){
        const aStart=foldText(a.author).startsWith(needle);
        const bStart=foldText(b.author).startsWith(needle);
        if(aStart!==bStart)return aStart?-1:1;
      }
      const diff=(b.total||0)-(a.total||0);
      if(diff!==0)return diff;
      return a.author.localeCompare(b.author);
    }).slice(0,50);

    menu.hidden=false;$('ghost').setAttribute('aria-expanded','true');
    tagMatches=matches.map(a=>({
      value:`@autor:${a.author}`,
      label:`@autor:${a.author}`,
      desc:`${a.total} ${a.total===1?'libro':'libros'}`,
      meta:'autor',
      type:'author',
      authorName:a.author
    }));
    tagSuggestionIndex=-1;$('ghost').removeAttribute('aria-activedescendant');
    const heading=after?'AUTORES DE LA BIBLIOTECA':'AUTORES RECIENTES Y FRECUENTES';
    if(tagMatches.length){
      menu.innerHTML=`<div class="suggestion-heading">${heading}</div>`+tagMatches.map((item,index)=>`
        <button type="button" id="tagSuggestion${index}" data-suggestion="${index}" role="option" aria-selected="false">
          <span class="suggestion-main">
            <span class="suggestion-cmd">${esc(item.label)}</span>
            <span class="suggestion-desc">${esc(item.desc)}</span>
          </span>
          <small class="suggestion-badge">${esc(item.meta)}</small>
        </button>
      `).join('');
    }else{
      menu.innerHTML=`<div class="suggestion-empty">Sin autores coincidentes con «${esc(after)}»</div>`;
    }
    positionTagSuggestions();
    return;
  }

  if(isLangSec){
    menu.dataset.variant='commands';
    const after=text.includes(':')?text.slice(text.indexOf(':')+1).trim():'';
    const needle=foldText(after);
    const langs=(S.languages||['Español','Inglés']).filter(l=>!needle||foldText(l).includes(needle));
    menu.hidden=false;$('ghost').setAttribute('aria-expanded','true');
    tagMatches=langs.map(l=>({
      value:`@idioma:${l}`,
      label:`@idioma:${l}`,
      desc:`Filtrar libros en ${l}`,
      meta:'idioma',
      type:'language'
    }));
    tagSuggestionIndex=-1;$('ghost').removeAttribute('aria-activedescendant');
    if(tagMatches.length){
      menu.innerHTML='<div class="suggestion-heading">IDIOMAS DISPONIBLES</div>'+tagMatches.map((item,index)=>`
        <button type="button" id="tagSuggestion${index}" data-suggestion="${index}" role="option" aria-selected="false">
          <span class="suggestion-main">
            <span class="suggestion-cmd">${esc(item.label)}</span>
            <span class="suggestion-desc">${esc(item.desc)}</span>
          </span>
          <small class="suggestion-badge">${esc(item.meta)}</small>
        </button>
      `).join('');
    }else{
      menu.innerHTML=`<div class="suggestion-empty">Sin idiomas coincidentes con «${esc(after)}»</div>`;
    }
    positionTagSuggestions();
    return;
  }

  if(isSortSec){
    menu.dataset.variant='commands';
    const after=text.includes(':')?text.slice(text.indexOf(':')+1).trim():'';
    const needle=foldText(after);
    const opts=SORT_OPTIONS_MENU.filter(o=>!needle||foldText(o.key).includes(needle)||foldText(o.label).includes(needle)||foldText(o.desc).includes(needle));
    menu.hidden=false;$('ghost').setAttribute('aria-expanded','true');
    tagMatches=opts.map(o=>({
      value:`@orden:${o.key}`,
      label:`@orden:${o.key}`,
      desc:o.desc,
      meta:'orden',
      type:'sort'
    }));
    tagSuggestionIndex=-1;$('ghost').removeAttribute('aria-activedescendant');
    menu.innerHTML='<div class="suggestion-heading">CRITERIOS DE ORDEN</div>'+tagMatches.map((item,index)=>`
      <button type="button" id="tagSuggestion${index}" data-suggestion="${index}" role="option" aria-selected="false">
        <span class="suggestion-main">
          <span class="suggestion-cmd">${esc(item.label)}</span>
          <span class="suggestion-desc">${esc(item.desc)}</span>
        </span>
        <small class="suggestion-badge">${esc(item.meta)}</small>
      </button>
    `).join('');
    positionTagSuggestions();
    return;
  }

  if(isFormatSec){
    menu.dataset.variant='commands';
    const after=text.includes(':')?text.slice(text.indexOf(':')+1).trim():'';
    const needle=foldText(after);
    const fmts=COMMON_FORMATS.filter(f=>!needle||foldText(f.fmt).includes(needle)||foldText(f.desc).includes(needle));
    menu.hidden=false;$('ghost').setAttribute('aria-expanded','true');
    tagMatches=fmts.map(f=>({
      value:`@formato:${f.fmt}`,
      label:`@formato:${f.fmt}`,
      desc:f.desc,
      meta:'formato',
      type:'format'
    }));
    tagSuggestionIndex=-1;$('ghost').removeAttribute('aria-activedescendant');
    menu.innerHTML='<div class="suggestion-heading">FORMATOS Y EXTENSIONES</div>'+tagMatches.map((item,index)=>`
      <button type="button" id="tagSuggestion${index}" data-suggestion="${index}" role="option" aria-selected="false">
        <span class="suggestion-main">
          <span class="suggestion-cmd">${esc(item.label)}</span>
          <span class="suggestion-desc">${esc(item.desc)}</span>
        </span>
        <small class="suggestion-badge">${esc(item.meta)}</small>
      </button>
    `).join('');
    positionTagSuggestions();
    return;
  }

  if(isRatingSec){
    menu.dataset.variant='commands';
    const after=text.includes(':')?text.slice(text.indexOf(':')+1).trim():'';
    const needle=foldText(after);
    const ratingOpts=[
      {val:'5',label:'5 estrellas',desc:'Máxima calificación'},
      {val:'>=4',label:'>=4 estrellas',desc:'4 estrellas o más'},
      {val:'3',label:'3 estrellas',desc:'Calificación media'},
      {val:'<=2',label:'<=2 estrellas',desc:'2 estrellas o inferior'},
      {val:'sin',label:'Sin calificación',desc:'Sin estrellas asignadas'}
    ].filter(r=>!needle||foldText(r.val).includes(needle)||foldText(r.label).includes(needle));
    menu.hidden=false;$('ghost').setAttribute('aria-expanded','true');
    tagMatches=ratingOpts.map(r=>({
      value:`@rating:${r.val}`,
      label:`@rating:${r.val}`,
      desc:r.desc,
      meta:'rating',
      type:'rating'
    }));
    tagSuggestionIndex=-1;$('ghost').removeAttribute('aria-activedescendant');
    menu.innerHTML='<div class="suggestion-heading">CALIFICACIÓN POR ESTRELLAS</div>'+tagMatches.map((item,index)=>`
      <button type="button" id="tagSuggestion${index}" data-suggestion="${index}" role="option" aria-selected="false">
        <span class="suggestion-main">
          <span class="suggestion-cmd">${esc(item.label)}</span>
          <span class="suggestion-desc">${esc(item.desc)}</span>
        </span>
        <small class="suggestion-badge">${esc(item.meta)}</small>
      </button>
    `).join('');
    positionTagSuggestions();
    return;
  }

  if(isTag){
    const prefix=text[0];
    const needle=foldText(text.slice(1));
    if(!tagCatalog){
      menu.hidden=false;$('ghost').setAttribute('aria-expanded','true');
      menu.innerHTML='<div class="suggestion-loading">Cargando etiquetas…</div>';
      positionTagSuggestions();
    }
    let catalog;
    try{catalog=await loadTagCatalog();}
    catch(err){
      if(revision===tagSuggestionRevision){
        menu.innerHTML='<div class="suggestion-empty">No se pudieron cargar las etiquetas</div>';
        positionTagSuggestions();
      }
      throw err;
    }
    if(revision!==tagSuggestionRevision||$('ghost').hidden||$('ghost').value.trim()!==text)return;
    const recentMap=getRecentTagMap();
    const getLocalRecency=item=>recentMap[String(item.tag||'').toLowerCase()]||'';
    tagMatches=(catalog||[]).filter(item=>!needle||foldText(item.tag).includes(needle)).sort((a,b)=>{
      const localA=getLocalRecency(a),localB=getLocalRecency(b);
      if(localA!==localB){
        if(!localA)return 1;
        if(!localB)return -1;
        return localB.localeCompare(localA);
      }
      const recA=a.recent||'',recB=b.recent||'';
      if(recA!==recB)return recB.localeCompare(recA);
      const left=foldText(a.tag),right=foldText(b.tag);
      if(needle&&left.startsWith(needle)!==right.startsWith(needle))return left.startsWith(needle)?-1:1;
      return (b.total||0)-(a.total||0)||left.localeCompare(right);
    }).slice(0,50).map(item=>({
      value:prefix+item.tag,
      label:prefix+item.tag,
      desc:`${item.total} ${item.total===1?'libro':'libros'}`,
      meta:prefix==='+'?'incluir':'excluir',
      type:'tag'
    }));
    tagSuggestionIndex=-1;$('ghost').removeAttribute('aria-activedescendant');
    menu.dataset.variant='tags';
    menu.hidden=false;$('ghost').setAttribute('aria-expanded','true');
    const heading=prefix==='+'?'ETIQUETAS (INCLUIR)':'ETIQUETAS (EXCLUIR)';
    if(tagMatches.length){
      menu.innerHTML=`<div class="suggestion-heading">${heading}</div>`+tagMatches.map((item,index)=>`
        <button type="button" id="tagSuggestion${index}" data-suggestion="${index}" role="option" aria-selected="false">
          <span class="suggestion-cmd">${esc(item.label)}</span>
          <small class="suggestion-count">${esc(item.desc)}</small>
        </button>
      `).join('');
    }else{
      menu.innerHTML=`<div class="suggestion-empty">Sin etiquetas coincidentes con «${esc(text)}»</div>`;
    }
    positionTagSuggestions();
    return;
  }

  const cmdMatches=getCommandMatches(text);
  if(cmdMatches.length){
    menu.dataset.variant='commands';
    menu.hidden=false;$('ghost').setAttribute('aria-expanded','true');
    tagMatches=cmdMatches.map(c=>({
      value:c.cmd,
      label:c.cmd,
      desc:c.desc,
      meta:'comando',
      type:'command'
    }));
    tagSuggestionIndex=-1;$('ghost').removeAttribute('aria-activedescendant');
    menu.innerHTML='<div class="suggestion-heading">COMANDOS SUGERIDOS</div>'+tagMatches.map((item,index)=>`
      <button type="button" id="tagSuggestion${index}" data-suggestion="${index}" role="option" aria-selected="false">
        <span class="suggestion-main">
          <span class="suggestion-cmd">${esc(item.label)}</span>
          <span class="suggestion-desc">${esc(item.desc)}</span>
        </span>
        <small class="suggestion-badge">${esc(item.meta)}</small>
      </button>
    `).join('');
    positionTagSuggestions();
    return;
  }

  hideTagSuggestions();
}

function moveTagSuggestion(direction){if(!tagMatches.length)return;if(tagSuggestionIndex<0){tagSuggestionIndex=direction>0?0:tagMatches.length-1;}else{tagSuggestionIndex=(tagSuggestionIndex+direction+tagMatches.length)%tagMatches.length;}let activeButton=null;$('tagSuggestions').querySelectorAll('[data-suggestion]').forEach((button,index)=>{const active=index===tagSuggestionIndex;button.classList.toggle('active',active);button.setAttribute('aria-selected',String(active));if(active)activeButton=button;});$('ghost').setAttribute('aria-activedescendant','tagSuggestion'+tagSuggestionIndex);if(activeButton)activeButton.scrollIntoView({block:'nearest'});}
function ghostShow(value){$('ghost').hidden=false;$('searchToggle').setAttribute('aria-expanded','true');if(value!==undefined)$('ghost').value=value;else if(S.view==='course')$('ghost').value=S.courseQuery;$('ghost').focus();if(S.view!=='course')setView('grid');if(value)queueSearch();else guard(updateTagSuggestions)();}
function ghostHide(){clearTimeout(ghostTimer);hideTagSuggestions();$('ghost').value='';$('ghost').hidden=true;$('searchToggle').setAttribute('aria-expanded','false');}
function queueSearch(){
  clearTimeout(ghostTimer);
  const draft=$('ghost').value.trim();
  if(draft.toLowerCase()==='.help'){guard(updateTagSuggestions)();return;}
  const isSpecial=/^[+@.\/-]/.test(draft);
  if(S.view==='course'){
    if(isSpecial||!draft){S.courseQuery='';guard(updateTagSuggestions)();}
    else{hideTagSuggestions();S.courseQuery=draft;}
    ghostTimer=setTimeout(()=>renderResources(),100);
    return;
  }
  if(isSpecial||!draft){guard(updateTagSuggestions)();return;}
  hideTagSuggestions();
  ghostTimer=setTimeout(guard(()=>refresh(true,true)),180);
}
$('searchToggle').onclick=guard(async()=>{if($('ghost').hidden)ghostShow();else{if($('ghost').value.trim().toLowerCase()==='.help'){ghostHide();openHelpModal();return;}ghostHide();if(S.view==='course')renderResources();else await refresh(true);}});
document.addEventListener('keydown',e=>{if(S.view==='course'&&e.key==='Escape'&&!$('ghost').hidden){e.preventDefault();e.stopImmediatePropagation();S.courseQuery='';ghostHide();renderResources();}},true);
$('searchToggle').onkeydown=e=>{if(!S.tokens.length)return;if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();focusFilter(e.key==='ArrowLeft'?S.tokens.length-1:0);}};
$('searchToggle').onpointerdown=e=>{if(!$('ghost').hidden)e.preventDefault();};
$('ghost').onblur=e=>{hideTagSuggestions();if(!$('ghost').value.trim()&&e.relatedTarget!==$('searchToggle')){ghostHide();if(!e.relatedTarget?.closest?.('#filters'))guard(()=>refresh(true))();}};
$('tagSuggestions').onpointerdown=e=>e.preventDefault();
$('tagSuggestions').onclick=guard(async e=>{
  const option=e.target.closest('[data-suggestion]');
  if(option){
    const idx=Number(option.dataset.suggestion);
    const item=tagMatches[idx];
    if(item){
      if(item.type==='state'&&item.stateId)recordRecentState(item.stateId);
      if(item.type==='author'&&item.authorName)recordRecentAuthor(item.authorName);
      await commitGhost(item.value);
    }
  }
});
async function commitGhost(value){
  clearTimeout(ghostTimer);
  const text=(value??$('ghost').value).trim();
  const low=text.toLowerCase();
  if(low==='.help'){ghostHide();openHelpModal();return;}
  if(low==='@confirmar:suprimir'){
    ghostHide();
    const enabled=!S.confirmDelete;
    await api('preference',{key:'confirm_delete',value:String(enabled)});
    S.confirmDelete=enabled;
    notify(enabled?'Confirmación de Suprimir activada':'Confirmación de Suprimir desactivada');
    return;
  }
  if(low.startsWith('@orden:')){
    ghostHide();
    await applySort(text.slice(7));
    return;
  }
  if(['idiomas','@idiomas','.idiomas','/idiomas'].includes(low)){
    ghostHide();openLanguagesModal();return;
  }
  if(['@recientes:titulos','@titulos:recientes','@historial:titulos'].includes(low)){
    ghostHide();
    S.showRecentTitles=!S.showRecentTitles;
    await api('preference',{key:'show_recent_titles',value:String(S.showRecentTitles)});
    localStorage.setItem('balisco.showRecentTitles',String(S.showRecentTitles));
    notify(S.showRecentTitles?'Títulos en búsquedas recientes: Activados':'Títulos en búsquedas recientes: Desactivados (solo etiquetas y comandos)');
    return;
  }
  if(low==='@barra'){
    ghostHide();
    setToolbarPosition(document.body.classList.contains('search-bottom')?'top':'bottom');
    notify(document.body.classList.contains('search-bottom')?'Búsqueda abajo':'Búsqueda arriba');
    return;
  }
  if(S.view==='course'){
    ghostHide();
    if(/^[+@-]/.test(text)||low.startsWith('autor:')){
      S.courseQuery='';
      if(text){
        if(text.startsWith('+')||text.startsWith('-'))recordRecentTag(text);
        if(low.startsWith('@autor:'))recordRecentAuthor(text.slice(7));
        await addToken(text);
      }
    }else{
      S.courseQuery=text;
      renderResources();
    }
    return;
  }
  if(!text)return;
  if(text==='+'||text==='-'||text==='@'||text==='.'||text==='/')return;
  if(text.endsWith(':')){
    $('ghost').hidden=false;$('ghost').value=text;$('ghost').focus();
    queueSearch();
    return;
  }
  ghostHide();
  recordSearchHistory(text);
  if(text.startsWith('+')||text.startsWith('-'))recordRecentTag(text);
  if(low.startsWith('@autor:'))recordRecentAuthor(text.slice(7));
  if(low.startsWith('@estado:'))recordRecentState(text.slice(8));
  if(document.activeElement instanceof HTMLElement)document.activeElement.blur();
  if(S.tokens.includes(text)){await refresh(true);return;}
  try{await addToken(text);}catch(error){ghostShow(text);throw error;}
}
document.addEventListener('keydown',guard(async e=>{const editing=e.target instanceof Element && e.target.matches('input,textarea,select,[contenteditable=true]');if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='f'&&!$('dialog').open){e.preventDefault();ghostShow();return;}if(e.key==='Escape'){if($('dialog').open){e.preventDefault();$('dialog').close();return;}if(e.target instanceof Element&&e.target.closest('#filters .chip')){e.preventDefault();e.target.blur();return;}if(!$('ghost').hidden){e.preventDefault();ghostHide();$('searchToggle').focus();await refresh(true);return;}if(editing){e.target.blur();return;}$('popover').hidden=true;S.tokens=[];await flush();if(S.view==='course'){S.courseQuery='';renderResources();return;}setView('grid');await refresh(true);return;}if($('dialog').open||editing)return;if(e.key==='Enter'&&!e.ctrlKey&&!e.metaKey&&!e.altKey&&!(e.target instanceof Element&&e.target.closest('button,.card,[role=button]'))){e.preventDefault();ghostShow();return;}if(!e.metaKey&&(e.key==='@'||((e.ctrlKey&&e.altKey||e.getModifierState?.('AltGraph'))&&['KeyQ','Digit2'].includes(e.code)))){e.preventDefault();ghostShow('@');return;}if(e.ctrlKey||e.metaKey||e.altKey||e.key.length!==1)return;if(e.key==='/'||/[\p{L}\p{N}+@-]/u.test(e.key)){e.preventDefault();ghostShow(e.key==='/'?'':e.key);}}));
$('ghost').onkeydown=guard(async e=>{
  if((e.key==='ArrowLeft'||e.key==='ArrowRight')&&!$('ghost').value&&S.tokens.length){
    e.preventDefault();
    focusFilter(e.key==='ArrowLeft'?S.tokens.length-1:0);
    return;
  }
  if((e.key==='ArrowDown'||e.key==='ArrowUp')&&!$('tagSuggestions').hidden){
    e.preventDefault();
    moveTagSuggestion(e.key==='ArrowDown'?1:-1);
    return;
  }
  if(e.key==='Tab'&&!$('tagSuggestions').hidden&&tagMatches.length){
    e.preventDefault();
    const idx=tagSuggestionIndex>=0?tagSuggestionIndex:0;
    const item=tagMatches[idx];
    if(item){
      if(item.type==='state'&&item.stateId)recordRecentState(item.stateId);
      if(item.type==='author'&&item.authorName)recordRecentAuthor(item.authorName);
      $('ghost').value=item.value;
      if(item.value.endsWith(':')){
        queueSearch();
      }else{
        hideTagSuggestions();
      }
      return;
    }
  }
  if(e.key==='Enter'){
    e.preventDefault();
    const rawGhost=$('ghost').value.trim();
    if(rawGhost.toLowerCase()==='.help'){ghostHide();openHelpModal();return;}
    let suggestion=undefined;
    if(tagSuggestionIndex>=0&&tagMatches[tagSuggestionIndex]){
      const sel=tagMatches[tagSuggestionIndex];
      if(sel.type==='state'&&sel.stateId)recordRecentState(sel.stateId);
      if(sel.type==='author'&&sel.authorName)recordRecentAuthor(sel.authorName);
      suggestion=sel.value;
    }
    await commitGhost(suggestion);
    return;
  }
  if(e.key==='Escape'&&!$('tagSuggestions').hidden){
    e.preventDefault();e.stopPropagation();hideTagSuggestions();return;
  }
  if(e.key==='Backspace'&&!$('ghost').value&&S.tokens.length){
    e.preventDefault();S.tokens.pop();await refresh(true);
  }
});
$('ghost').oninput=queueSearch;
window.addEventListener('keydown',e=>{if(e.key==='Escape'){if($('coverDialog')?.open){e.preventDefault();e.stopImmediatePropagation();$('coverDialog').close();return;}if($('dialog')?.open){e.preventDefault();e.stopImmediatePropagation();$('dialog').close();}}},true);
$('dialog').addEventListener('cancel',e=>{e.preventDefault();$('dialog').close();});
$('dialog').addEventListener('close',()=>{
 $('dialogTitle').replaceChildren();
 $('dialogBody').replaceChildren();
 if(document.activeElement&&document.activeElement.closest?.('#dialog'))document.activeElement.blur();
});
$('dialog').addEventListener('click',e=>{
 if(e.target.closest('.help-close-btn,#helpCloseBtn')){e.preventDefault();e.stopPropagation();$('dialog').close();return;}
 if(e.target===$('dialog')){const r=$('dialog').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)$('dialog').close();}
});
function openHelpModal(){
 const dialog=$('dialog');if(dialog.open)return;if(document.activeElement instanceof HTMLElement)document.activeElement.blur();
 $('dialogTitle').innerHTML='<div class="help-header"><span class="help-title">Guía de Comandos y Filtros</span><button type="button" class="help-close-btn" id="helpCloseBtn" onclick="document.getElementById(\'dialog\').close()" aria-label="Cerrar modal" title="Cerrar (Escape)">✕</button></div>';
 const closeBtn=$('dialogTitle').querySelector('#helpCloseBtn');
 if(closeBtn)closeBtn.onclick=e=>{e.preventDefault();e.stopPropagation();dialog.close();};
 const sections=[
  {
   title:'Calificación (Rating)',
   items:[
    {cmd:'@rating:1-3',desc:'Rango de 1 a 3 estrellas'},
    {cmd:'@rating:>=4',desc:'4 estrellas o más (o 4+)'},
    {cmd:'@rating:<=2',desc:'2 estrellas o menos'},
    {cmd:'@rating:1,3,5',desc:'Calificaciones exactas'},
    {cmd:'@rating:sin',desc:'Sin calificación (o @rating:0)'}
   ]
  },
  {
   title:'Tipos y Formatos',
   items:[
    {cmd:'@tipo:documento,video',desc:'Varios tipos a la vez'},
    {cmd:'@tipo:contenedor',desc:'Solo contenedores y cursos'},
    {cmd:'@formato:epub,pdf',desc:'Formatos por extensión'},
    {cmd:'@fmt:mkv',desc:'Alias corto de formato'}
   ]
  },
  {
   title:'Tamaño y Peso',
   items:[
    {cmd:'@peso:>100mb',desc:'Archivos mayores a 100 MB'},
    {cmd:'@peso:<10mb',desc:'Archivos menores a 10 MB'},
    {cmd:'@peso:50mb-200mb',desc:'Rango de tamaño'},
    {cmd:'@peso:>1gb',desc:'Archivos mayores a 1 GB'}
   ]
  },
  {
   title:'Etiquetas y Autores',
   items:[
    {cmd:'+etiqueta',desc:'Incluir etiqueta (recientes primero)'},
    {cmd:'-etiqueta',desc:'Excluir etiqueta'},
    {cmd:'+arte|musica',desc:'Etiqueta arte O musica'},
    {cmd:'@autor:nombre',desc:'Buscar por autor'}
   ]
  },
  {
   title:'Estados de Lectura',
   items:[
    {cmd:'@pendiente',desc:'Elemento pendiente'},
    {cmd:'@leyendo',desc:'Actualmente leyendo'},
    {cmd:'@leido',desc:'Elemento completado'},
    {cmd:'@estado:pendiente,leyendo',desc:'Múltiples estados'},
    {cmd:'@!leido',desc:'Excluir estado (o -@leido)'}
   ]
  },
  {
   title:'Mantenimiento y Filtros Rápidos',
   items:[
    {cmd:'@sin:miniatura',desc:'Sin miniatura o portada (o @sin:portada)'},
    {cmd:'@con:miniatura',desc:'Con miniatura o portada (o @con:portada)'},
    {cmd:'@sin:etiquetas',desc:'Archivos sin etiquetas'},
    {cmd:'@con:etiquetas',desc:'Archivos con etiquetas'},
    {cmd:'@sin:notas',desc:'Archivos sin notas'},
    {cmd:'@con:notas',desc:'Archivos con notas'},
    {cmd:'@con:seguimiento',desc:'Favorito, calificación, estado avanzado o notas'},
    {cmd:'@sin:autor',desc:'Archivos sin autor'},
    {cmd:'@favoritos',desc:'Tus elementos favoritos'},
    {cmd:'@recientes',desc:'Archivos abiertos recientemente'},
    {cmd:'@ocultos',desc:'Mostrar elementos ocultos'}
   ]
  },
  {
   title:'Atajos y Comandos del Sistema',
   items:[
    {cmd:'@idiomas',desc:'Administrar idiomas disponibles'},
    {cmd:'@recientes:titulos',desc:'Mostrar u ocultar títulos en búsquedas recientes'},
    {cmd:'@barra',desc:'Alternar barra arriba / abajo'},
    {cmd:'@confirmar:suprimir',desc:'Activar o desactivar la confirmación de Suprimir'},
    {cmd:'@orden:peso',desc:'Ordenar por mayor tamaño'},
    {cmd:'@orden:recientes',desc:'Ordenar por recientes'},
    {cmd:'.help',desc:'Abrir esta ventana de ayuda'}
   ]
  }
 ];
 let html='<p class="help-lead">Haz clic en cualquier comando para aplicarlo directamente en el buscador:</p><div class="help-dialog-body">';
 for(const sec of sections){
  html+=`<div class="help-section"><div class="help-section-title">${esc(sec.title)}</div><div class="help-grid">`;
  for(const item of sec.items){
   html+=`<button type="button" class="help-item" data-help-cmd="${esc(item.cmd)}"><span class="help-cmd">${esc(item.cmd)}</span><span class="help-desc" title="${esc(item.desc)}">${esc(item.desc)}</span></button>`;
  }
  html+='</div></div>';
 }
 html+='</div>';
 $('dialogBody').innerHTML=html;
 $('dialogBody').onclick=guard(async e=>{
  const item=e.target.closest('[data-help-cmd]');
  if(!item)return;
  const cmd=item.dataset.helpCmd;
  dialog.close();
  if(cmd==='.help')return;
  if(cmd==='@recientes:titulos'||cmd==='@titulos:recientes'||cmd==='@historial:titulos'){await commitGhost(cmd);return;}
  if(cmd==='@confirmar:suprimir'){await commitGhost(cmd);return;}
  if(cmd==='idiomas'||cmd==='@idiomas'){openLanguagesModal();return;}
  if(cmd==='@barra'){
   setToolbarPosition(document.body.classList.contains('search-bottom')?'top':'bottom');
   notify(document.body.classList.contains('search-bottom')?'Búsqueda abajo':'Búsqueda arriba');
   return;
  }
  if(cmd.startsWith('@orden:')){
   await applySort(cmd.slice(7));
   return;
  }
  await addToken(cmd);
 });
 dialog.showModal();
}
function stars(container,value,callback){container.classList.add('stars');container.innerHTML=Array.from({length:5},(_,i)=>`<button class="${i<value?'on':''}" aria-label="${i+1} estrellas" title="${i+1} estrellas" data-rating="${i+1}">${icon('star')}</button>`).join('');container.onpointerover=e=>{const n=+e.target.closest('[data-rating]')?.dataset.rating;container.querySelectorAll('button').forEach((b,i)=>b.classList.toggle('preview',i<n));};container.onpointerleave=()=>container.querySelectorAll('button').forEach(b=>b.classList.remove('preview'));container.onclick=guard(e=>{const n=+e.target.closest('[data-rating]')?.dataset.rating;if(n)return callback(n);});}
let popoverAnchor=null,popoverCloseTimer=null;
setToolbarPosition(localStorage.getItem('balisco.toolbarPosition')==='bottom'?'bottom':'top');
function pop(anchor){const el=$('popover');clearTimeout(popoverCloseTimer);popoverCloseTimer=null;el.classList.remove('is-closing');if(!el.hidden&&popoverAnchor===anchor){el.hidden=true;popoverAnchor=null;return null;}popoverAnchor=anchor;$('importPanel').hidden=true;el.replaceChildren();el.className='popover';el.style.left='auto';el.style.top='60px';el.style.right=Math.max(12,innerWidth-anchor.getBoundingClientRect().right)+'px';el.hidden=false;return el;}
function closeRepeatedItemActions(anchor){const el=$('popover');if(el.hidden||popoverAnchor!==anchor||!el.classList.contains('item-actions'))return false;popoverAnchor=null;el.classList.add('is-closing');clearTimeout(popoverCloseTimer);popoverCloseTimer=setTimeout(()=>{el.hidden=true;el.classList.remove('is-closing');popoverCloseTimer=null;},250);return true;}
$('popover').addEventListener('contextmenu',e=>{if(!$('popover').classList.contains('item-actions'))return;e.preventDefault();e.stopPropagation();if(popoverAnchor)closeRepeatedItemActions(popoverAnchor);});
function positionToolbarPopover(el,anchor){const rect=anchor.getBoundingClientRect(),left=Math.max(8,Math.min(rect.left,innerWidth-el.offsetWidth-8)),below=rect.bottom+6;el.style.left=left+'px';el.style.right='auto';el.style.top=(below+el.offsetHeight>innerHeight-8?Math.max(8,rect.top-el.offsetHeight-6):below)+'px';}
async function openItemActions(anchor,ids,course=false,point=null){
 if(!ids.length&&!course)return;
 let first=null;if(ids.length){try{first=await api('detail',{id:ids[0]});}catch(error){if(!course)throw error;}}
 const selectionCount=course?Math.max(ids.length,S.courseSelectedKeys.size):ids.length;
 let properties=selectionCount>ids.length?{fijado:null,es_favorito:null,oculto:null,rating:null,estado_lectura:null}:first;
 if(ids.length>1&&selectionCount===ids.length){try{properties=await api('selection_properties',{ids});}catch(error){if(!course)throw error;properties={fijado:null,es_favorito:null,oculto:null,rating:null,estado_lectura:null};}}
 const recentAvailable=!!first&&(ids.length>1?properties.recent_count>0:!!first.ultimo_acceso&&!first.recent_hidden)&&(!course||selectionCount===ids.length&&courseSelectedRows().every(row=>!row.hasAttribute('data-folder')));
 if(point){$('popover').hidden=true;popoverAnchor=null;}
 const el=pop(anchor);if(!el)return;
 el.classList.add('item-actions');
 const choice=(action,symbol,label,active=false)=>`<button type="button" data-item-action="${action}" class="item-action-row ${active?'is-active':''}" ${action==='visible'?'':`aria-pressed="${!!active}"`}>${icon(symbol)}<span>${label}</span></button>`;
 el.innerHTML=(selectionCount>1?`<div class="item-actions-heading">${selectionCount} elementos seleccionados</div>`:'')+
   (first?`<div class="item-actions-group">${choice('pin','pin',properties.fijado===1?'Desfijar de biblioteca':'Fijar en biblioteca',properties.fijado===1)}${choice('favorite','heart',properties.es_favorito===1?'Quitar de favoritos':'Agregar a favoritos',properties.es_favorito===1)}${choice('visible',properties.oculto===0?'eyeOff':'eye',properties.oculto===0?'Ocultar de biblioteca':'Mostrar en biblioteca')}${recentAvailable?choice('remove-recent','recentOff','Quitar de recientes'):''}</div>`+
   `<div class="item-actions-group"><div class="item-actions-label">CALIFICACIÓN</div><div class="item-actions-rating">${Array.from({length:5},(_,i)=>`<button type="button" data-item-rating="${i+1}" aria-label="${i+1} estrellas" title="${i+1} estrellas · vuelve a pulsar para quitar" aria-pressed="${properties.rating===i+1}" class="${properties.rating!==null&&i<properties.rating?'on':''}">${icon('star')}</button>`).join('')}</div><div class="item-actions-states" role="group" aria-label="Estado de lectura">${states.map(state=>`<button type="button" data-item-state="${state}" title="${stateNames[state]}" aria-label="${stateNames[state]}" aria-pressed="${properties.estado_lectura===state}"><span class="state-indicator ${state}"></span></button>`).join('')}</div></div>`:'')+
   `<div class="item-actions-group">${first?choice('cover-options','image',selectionCount>1?'Opciones de portadas…':'Opciones de portada…'):''}${first?`<div class="item-action-submenu-wrap"><button type="button" data-item-submenu="render-cover" class="item-action-row has-submenu" aria-haspopup="menu" aria-expanded="false">${icon('render')}<span>${selectionCount>1?'Renderizar portadas':'Renderizar portada'}</span>${icon('chevronRight','submenu-arrow')}</button><div class="item-action-submenu" role="menu" hidden>${choice('cover-local','local','Renderizar aquí')}${choice('cover-colab','cloud','Usar Colab')}</div></div>`:''}${choice('open-panel','sidebar',$('inspector').classList.contains('is-compact')?'Abrir panel lateral':'Cerrar panel lateral')}${first&&first.tipo!=='curso'?choice('assign','package','Asignar a contenedor…'):''}${course?choice('storage','folder','Extraer a la biblioteca'):''}</div>`;
 if(point){el.style.right='auto';el.style.left=Math.max(8,Math.min(point.x,innerWidth-el.offsetWidth-8))+'px';el.style.top=Math.max(8,point.y+el.offsetHeight+8>innerHeight?point.y-el.offsetHeight:point.y)+'px';}
 const apply=async(field,value)=>{el.hidden=true;popoverAnchor=null;await api('bulk_update',{ids,field,value});if(S.selected&&ids.includes(S.selected.drive_id)){S.selected[field]=value;renderDetail(S.selected);}for(const row of S.resources)if(ids.includes(row.id))row[field]=value;await refresh();if(field==='oculto'&&value)notify('Oculto. Busca @ocultos para volver a mostrarlo.');};
 const submenuWrap=el.querySelector('.item-action-submenu-wrap'),submenuBtn=submenuWrap?.querySelector('[data-item-submenu]'),submenu=submenuWrap?.querySelector('.item-action-submenu');const openSubmenu=()=>{if(!submenu||!submenuBtn)return;submenu.hidden=false;submenu.classList.remove('flip-left','flip-up');submenuBtn.setAttribute('aria-expanded','true');const wrapRect=submenuWrap.getBoundingClientRect(),subRect=submenu.getBoundingClientRect();if(wrapRect.right+subRect.width+10>innerWidth)submenu.classList.add('flip-left');if(wrapRect.top+subRect.height+8>innerHeight)submenu.classList.add('flip-up');};const closeSubmenu=()=>{if(!submenu||!submenuBtn)return;submenu.hidden=true;submenuBtn.setAttribute('aria-expanded','false');};if(submenuWrap){submenuWrap.addEventListener('pointerenter',openSubmenu);submenuWrap.addEventListener('pointerleave',closeSubmenu);}el.onclick=guard(async e=>{if(e.target.closest('[data-item-submenu]')){e.stopPropagation();openSubmenu();return;}const rating=e.target.closest('[data-item-rating]');if(rating){const value=Number(rating.dataset.itemRating);await apply('rating',properties.rating===value?0:value);return;}const state=e.target.closest('[data-item-state]');if(state){await apply('estado_lectura',state.dataset.itemState);return;}const action=e.target.closest('[data-item-action]')?.dataset.itemAction;if(!action)return;el.hidden=true;popoverAnchor=null;if(action==='cover-options'){openCoverDialog(first,course?S.course?.drive_id:null,ids);return;}if(action==='cover-local'||action==='cover-colab'){await renderCovers(ids,action==='cover-local'?'local':'colab');return;}if(action==='open-panel'){setInspectorCompact(!$('inspector').classList.contains('is-compact'));return;}if(action==='storage'){await moveSelectedCourseToStorage();return;}if(action==='assign'){$('containerProperty')?.click();return;}if(action==='remove-recent'){const result=await api('bulk_remove_recent',{ids});for(const row of S.resources)if(ids.includes(row.id))row.recent_hidden=1;await refresh();notify(result.updated===1?'Quitado de recientes':`${result.updated} elementos quitados de recientes`);return;}if(!first)return;const field={pin:'fijado',favorite:'es_favorito',visible:'oculto'}[action];if(field)await apply(field,field==='oculto'?properties.oculto===0:properties[field]!==1);});
}
$('rating').onclick=()=>{const el=pop($('rating'));if(!el)return;stars(el,0,async n=>{$('popover').hidden=true;popoverAnchor=null;await toggleFacet('@rating:','@rating:'+n);});};
$('favorite').onclick=guard(async()=>{await flush();if(S.tokens.includes('@favoritos')){S.tokens=S.tokens.filter(token=>token!=='@favoritos');if(S.view!=='course')setView('grid');await refresh(true);}else await addToken('@favoritos');});
$('statusFilter').onclick=()=>{const el=pop($('statusFilter'));if(!el)return;const current=[...S.tokens].reverse().find(token=>filterStates.some(state=>token==='@'+state));el.classList.add('state-popover');el.innerHTML=`<button class="state-choice" data-reading="" title="Todos los estados" aria-label="Todos los estados" ${current?'':'aria-current="true"'}><span class="state-indicator all"></span></button>`+filterStates.map(state=>`<button class="state-choice" draggable="true" data-reading="${state}" title="${stateNames[state]}" aria-label="${stateNames[state]}" ${current==='@'+state?'aria-current="true"':''}><span class="state-indicator ${state}"></span></button>`).join('');positionToolbarPopover(el,$('statusFilter'));let draggedState=null,wasDragging=false;
 el.ondragstart=event=>{const choice=event.target.closest('[data-reading]');if(!choice?.dataset.reading){event.preventDefault();return;}draggedState=choice.dataset.reading;wasDragging=true;event.dataTransfer.effectAllowed='move';};
 el.ondragover=event=>{if(draggedState&&event.target.closest('[data-reading]'))event.preventDefault();};
 el.ondrop=event=>{event.preventDefault();const target=event.target.closest('[data-reading]')?.dataset.reading;if(!draggedState||!target||target===draggedState)return;filterStates=filterStates.filter(x=>x!==draggedState);filterStates.splice(filterStates.indexOf(target),0,draggedState);localStorage.setItem('balisco.stateOrder',JSON.stringify(filterStates));const buttons=[...el.querySelectorAll('[data-reading]')];for(const state of filterStates){const button=buttons.find(x=>x.dataset.reading===state);el.append(button);}draggedState=null;};
 el.ondragend=()=>{draggedState=null;setTimeout(()=>{wasDragging=false;},0);};
 el.onclick=guard(async event=>{if(wasDragging)return;const option=event.target.closest('[data-reading]');if(!option)return;const state=option.dataset.reading;el.hidden=true;popoverAnchor=null;if(state)await toggleFacetState(state);else{S.tokens=S.tokens.filter(token=>!filterStates.some(value=>token==='@'+value));await flush();if(S.view!=='course')setView('grid');await refresh(true);}});};
 $('type').onclick=()=>{const el=pop($('type'));if(!el)return;el.classList.add('type-popover');const render=()=>{el.innerHTML=filterTypes.map(value=>`<button class="type-choice" draggable="true" data-type="${value}" title="${typeNames[value]} · arrastra para cambiar el orden" aria-label="${typeNames[value]}" ${S.tokens.includes('@tipo:'+value)?'aria-current="true"':''}>${icon(typeIcons[value])}</button>`).join('');positionToolbarPopover(el,$('type'));};render();let draggedType=null,wasDragging=false;el.ondragstart=e=>{const choice=e.target.closest('[data-type]');if(!choice)return;draggedType=choice.dataset.type;wasDragging=true;e.dataTransfer.effectAllowed='move';};el.ondragover=e=>{if(draggedType&&e.target.closest('[data-type]'))e.preventDefault();};el.ondrop=e=>{e.preventDefault();const target=e.target.closest('[data-type]')?.dataset.type;if(!draggedType||!target||target===draggedType)return;filterTypes=filterTypes.filter(value=>value!==draggedType);filterTypes.splice(filterTypes.indexOf(target),0,draggedType);localStorage.setItem('balisco.typeOrder',JSON.stringify(filterTypes));draggedType=null;render();};el.ondragend=()=>{draggedType=null;setTimeout(()=>{wasDragging=false;},0);};el.onclick=guard(async e=>{if(wasDragging)return;const type=e.target.closest('[data-type]')?.dataset.type;if(type){el.hidden=true;popoverAnchor=null;await toggleFacet('@tipo:','@tipo:'+type);}});};
const sortOptions=[['recientes','Actividad reciente'],['antiguos','Más antiguos'],['abiertos','Últimos abiertos'],['peso','Mayor tamaño'],['ligero','Menor tamaño'],['alfabetico','Alfabético A–Z'],['natural','Orden natural']];
function selectedSort(){return [...S.tokens].reverse().find(t=>t.startsWith('@orden:'))?.slice(7)||null;}
function currentSort(){return selectedSort()||'recientes';}
async function applySort(key){if(key!=='natural'){await toggleFacet('@orden:','@orden:'+key);return;}const previous=[...S.tokens];S.tokens=S.tokens.filter(token=>!token.startsWith('@orden:'));try{await flush();if(S.view!=='course')setView('grid');await refresh(true);}catch(error){S.tokens=previous;renderFilters();throw error;}}
function showSortMenu(){const el=pop($('sort'));if(!el)return;el.classList.add('sort-popover');const selected=selectedSort();el.innerHTML=`<button data-recent="true" aria-current="${S.tokens.includes('@recientes')}"><span>Recientes abiertos</span><span>${S.tokens.includes('@recientes')?'✓':''}</span></button>`+sortOptions.map(([key,label])=>`<button data-sort="${key}" aria-current="${key!=='natural'&&selected===key}"><span>${esc(label)}</span><span>${key!=='natural'&&selected===key?'✓':''}</span></button>`).join('');positionToolbarPopover(el,$('sort'));el.onclick=guard(async e=>{if(e.target.closest('[data-recent]')){el.hidden=true;popoverAnchor=null;if(S.tokens.includes('@recientes'))S.tokens=S.tokens.filter(token=>token!=='@recientes');else S.tokens.push('@recientes');await refresh(true);return;}const key=e.target.closest('[data-sort]')?.dataset.sort;if(!key)return;el.hidden=true;popoverAnchor=null;await applySort(key);});}
$('sort').onclick=showSortMenu;
$('sort').addEventListener('wheel',e=>{e.preventDefault();const index=sortOptions.findIndex(([key])=>key===(selectedSort()||'natural'));const next=(index+(e.deltaY>0?1:-1)+sortOptions.length)%sortOptions.length;guard(()=>applySort(sortOptions[next][0]))();},{passive:false});
function wheelFacet(id,step){
 const state=[...S.tokens].reverse().find(t=>filterStates.includes(t.slice(1)))?.slice(1);
 const rating=[...S.tokens].reverse().find(t=>/^@rating:[1-5]$/.test(t));
 const type=[...S.tokens].reverse().find(t=>t.startsWith('@tipo:')&&['documento','contenedor','video','audio','imagen','otro'].includes(t.slice(6)))?.slice(6);
 if(id==='favorite')return toggleFacet('@favoritos','@favoritos');
 if(id==='statusFilter'){
  const index=Math.max(0,filterStates.indexOf(state)+1),next=Math.max(0,Math.min(filterStates.length,index+step));
  if(next===index)return;
  if(next===0){S.tokens=S.tokens.filter(t=>!filterStates.some(value=>t==='@'+value));return flush().then(()=>{if(S.view!=='course')setView('grid');return refresh(true);});}
  return toggleFacetState(filterStates[next-1]);
 }
 if(id==='rating'){
  const index=rating?Number(rating.slice(8)):0,next=Math.max(0,Math.min(5,index+step));
  if(next===index)return;
  if(next===0){S.tokens=S.tokens.filter(t=>!t.startsWith('@rating:'));return flush().then(()=>{if(S.view!=='course')setView('grid');return refresh(true);});}
  return toggleFacet('@rating:','@rating:'+next);
 }
 const types=filterTypes,index=type?types.indexOf(type)+1:0,next=Math.max(0,Math.min(types.length,index+step));
 if(next===index)return;
 if(next===0){S.tokens=S.tokens.filter(t=>!t.startsWith('@tipo:'));return flush().then(()=>{if(S.view!=='course')setView('grid');return refresh(true);});}
 return toggleFacet('@tipo:','@tipo:'+types[next-1]);
}
for(const id of ['favorite','statusFilter','rating','type'])$(id).addEventListener('wheel',e=>{
 e.preventDefault();if(!e.deltaY)return;guard(()=>wheelFacet(id,e.deltaY<0?1:-1))();
},{passive:false});
document.addEventListener('pointerdown',e=>{if(!e.target.closest('#wallpaperContextMenu'))wallpaperContextMenu.hidden=true;const sameItemRightClick=e.button===2&&!$('popover').hidden&&$('popover').classList.contains('item-actions')&&popoverAnchor?.contains(e.target);if(!sameItemRightClick&&!e.target.closest('#popover,#wallpaperContextMenu')&&!popoverAnchor?.contains(e.target)){$('popover').hidden=true;popoverAnchor=null;}});
function updateBulkButton(){const notice=$('bulkNotice');if(notice){notice.textContent=S.bulkIds.size>1?String(S.bulkIds.size):'';notice.hidden=S.bulkIds.size<=1;}}
function clearGridSelection(){if(!S.selected&&!S.bulkIds.size)return;S.selectionRevision++;S.selected=null;S.bulkIds.clear();selectionAnchorId=null;$('details').hidden=true;$('inspectorEmpty').hidden=false;updateBulkButton();scheduleDraw();}
document.addEventListener('click',e=>{if(suppressCardClick||e.target.closest('.card,[data-resource-key],#inspector,#popover,#dialog,#coverDialog,#inspectorToggle'))return;if(S.view==='grid')clearGridSelection();else if(S.view==='course'&&!courseSuppressClick&&S.courseSelection)clearCourseSelection();});
async function selectGridRange(id,extend=false){const end=S.items.findIndex(item=>item.drive_id===id),start=S.items.findIndex(item=>item.drive_id===selectionAnchorId);if(end<0)return;if(start<0){selectionAnchorId=id;return select(id);}const ids=S.items.slice(Math.min(start,end),Math.max(start,end)+1).map(item=>item.drive_id);S.bulkIds=new Set(extend?[...S.bulkIds,...ids]:ids);await select(id,true,true);updateBulkButton();scheduleDraw();}
async function toggleBulkSelection(id){if(S.bulkIds.has(id)){S.bulkIds.delete(id);if(S.selected?.drive_id===id){const last=[...S.bulkIds].at(-1);if(last)await select(last,true,true);else{S.selected=null;$('details').hidden=true;$('inspectorEmpty').hidden=false;}}}else{S.bulkIds.add(id);await select(id,true,true);}updateBulkButton();scheduleDraw();}
async function bulkMetadata(field,operation,value){await flush();if(!S.bulkIds.size)throw Error('Selecciona al menos un elemento.');const ids=[...S.bulkIds];const result=await api('bulk_metadata',{ids,field,operation,value});if(field==='autor')authorCatalog=null;else if(field==='etiquetas'){tagCatalog=null;if(operation==='add'||operation==='set')recordRecentTag(value);}if(S.view==='course')for(const row of S.resources)if(ids.includes(row.id)){if(field==='etiquetas'){const names=[...new Set(String(row.etiquetas||'').split(/\s+/).filter(Boolean))],tag='+'+value.replace(/^\+/,'');if(operation==='add'&&!names.includes(tag))names.push(tag);else if(operation==='remove')names.splice(0,names.length,...names.filter(name=>name!==tag));else if(operation==='set'){names.splice(0,names.length,tag,...names.filter(name=>name!==tag));}row.etiquetas=names.join(' ');}else{const names=new Set(String(row.autor||'').split('\n').filter(Boolean));if(operation==='add')names.add(value);else names.delete(value);row.autor=[...names].join('\n');}}if(S.selected&&S.bulkIds.has(S.selected.drive_id)){S.selected=await api('detail',{id:S.selected.drive_id});renderDetail(S.selected);}await refresh(false);updateBulkButton();notify(`${result.updated} elementos actualizados`);}
async function select(id,force=false,preserve=false){if(S.pinned&&S.selected&&!force)return;if(!preserve)S.bulkIds=new Set([id]);const revision=++S.selectionRevision;const isDifferent=S.selected?.drive_id!==id;if(isDifferent){for(const [cardId,node] of S.rows){node.classList.toggle('selected',cardId===id);if(!preserve)node.classList.toggle('bulk-selected',cardId===id);}const preview=S.items.find(i=>i.drive_id===id);if(preview){S.selected=preview;renderDetail(preview,true);}}await flush();const item=await api('detail',{id});if(revision!==S.selectionRevision)return;S.selected=item;renderDetail(item,isDifferent&&!S.items.some(i=>i.drive_id===id));scheduleDraw();}
function authorNames(value){return String(value||'').split(/\r?\n/).map(name=>name.trim()).filter(Boolean);}
function resizeDetailTitle(){const title=$('title');title.style.height='auto';title.style.height=Math.min(126,Math.max(27,title.scrollHeight))+'px';}

function populateLanguageSelect(selectedVal, isMixed=false){
 const sel=$('itemLanguage');
 if(!sel)return;
 let html='<option value="">Sin especificar</option>';
 for(const lang of (S.languages||[])){
  html+=`<option value="${esc(lang)}">${esc(lang)}</option>`;
 }
 if(isMixed){
  html='<option value="" disabled selected>Varios idiomas</option>'+html;
  sel.innerHTML=html;
 }else{
  sel.innerHTML=html;
  sel.value=selectedVal||'';
 }
}
function renderLanguagesList(){
 const list=$('languagesList');
 if(!list)return;
 if(!S.languages||!S.languages.length){
  list.innerHTML='<div class="language-empty" style="color:var(--muted);font-size:12px;padding:8px 0;">No hay idiomas configurados</div>';
  return;
 }
 list.innerHTML=S.languages.map(lang=>`
  <div class="language-item">
   <span>${esc(lang)}</span>
   <button type="button" class="language-del-btn" data-del-lang="${esc(lang)}" title="Eliminar idioma ${esc(lang)}" aria-label="Eliminar ${esc(lang)}">✕</button>
  </div>
 `).join('');
}
function openLanguagesModal(){
 renderLanguagesList();
 $('languagesDialog').showModal();
 $('languageInput').value='';
 $('languageInput').focus();
}
function renderDetail(item,animate=false){$('inspectorEmpty').hidden=true;$('details').hidden=false;if(animate){$('inspectorContent').scrollTop=0;animateInspectorSelection();$('details').classList.remove('detail-swap');void $('details').offsetWidth;$('details').classList.add('detail-swap');}$('details').classList.toggle('bulk-editing',S.bulkIds.size>1);$('title').value=item.titulo||'';$('title').readOnly=S.bulkIds.size>1;resizeDetailTitle();$('notes').value=item.notas||'';$('notes').readOnly=S.bulkIds.size>1;$('driveUrl').textContent=item.url||'';$('readingState').value=item.estado_lectura||'pendiente';const heroArt=$('heroArt');const cachedCover=getCachedCover(item.drive_id);if(cachedCover){heroArt.dataset.coverId=item.drive_id;heroArt.innerHTML=`<img src="${cachedCover}" alt="Portada" class="hero-cover">`;}else if(item.has_cover===false){heroArt.dataset.coverId=item.drive_id;heroArt.innerHTML=art(item);}else{if(heroArt.dataset.coverId!==item.drive_id){heroArt.dataset.coverId=item.drive_id;heroArt.innerHTML=art(item);}loadCover(item.drive_id).then(src=>{if(src&&S.selected?.drive_id===item.drive_id&&heroArt.dataset.coverId===item.drive_id){heroArt.innerHTML=`<img src="${src}" alt="Portada" class="hero-cover">`;}}).catch(report);}$('saveState').textContent='';updateBulkButton();
 if(S.bulkIds.size>1){
  const selectedItems=S.items.filter(i=>S.bulkIds.has(i.drive_id));
  const langs=new Set(selectedItems.map(i=>i.idioma||''));
  if(langs.size>1)populateLanguageSelect('',true);
  else populateLanguageSelect(selectedItems[0]?.idioma||'',false);
 }else{
  populateLanguageSelect(item.idioma||'',false);
 }
 const tags=(item.etiquetas||'').split(/\s+/).filter(Boolean),physicalParent=String(item.ruta_relativa||'').split('\\').slice(0,-1).join('\\');$('itemTags').innerHTML=tags.map((t,index)=>`<button class="tag ${index===0?'primary':''}" draggable="${S.bulkIds.size===1&&!item.container_parent}" data-tag="${esc(t)}" data-tag-index="${index}" title="${index===0?`📁 ${esc(physicalParent)} · `:''}Arrastra para ordenar; clic para filtrar; clic derecho para quitar">${index===0?'📁 ':''}${esc(t)}</button>`).join('')+`<button class="tag" id="addTag" aria-label="Añadir etiqueta">${icon('plus')}</button>`;
 $('addTag').onclick=()=>{const form=$('tagForm');form.hidden=!form.hidden;$('addTag').setAttribute('aria-expanded',String(!form.hidden));if(!form.hidden)$('tagInput').focus();};$('tagForm').hidden=true;$('addTag').setAttribute('aria-expanded','false');
 $('primaryTagButton')?.remove();if(S.bulkIds.size>1){const primary=document.createElement('button');primary.id='primaryTagButton';primary.type='button';primary.className='text-button';primary.textContent='Usar como carpeta';primary.title='Poner esta etiqueta primero sin borrar las etiquetas propias de cada elemento';primary.onclick=guard(async()=>{const tag=$('tagInput').value.trim();if(tag){await bulkMetadata('etiquetas','set',tag);$('tagInput').value='';}});$('tagForm').append(primary);}
 $('itemAuthors').innerHTML=authorNames(item.autor).map((name,index)=>`<span class="author-chip"><span title="${esc(name)}">${esc(name)}</span><button type="button" data-author-remove="${index}" aria-label="Quitar autor ${esc(name)}" title="Quitar autor">${icon('close')}</button></span>`).join('')+`<button type="button" class="tag" id="addAuthor" aria-label="Añadir autor" title="Añadir autor">${icon('plus')}</button>`;
 $('addAuthor').onclick=()=>{const form=$('authorForm');form.hidden=!form.hidden;$('addAuthor').setAttribute('aria-expanded',String(!form.hidden));if(!form.hidden)$('authorInput').focus();};$('authorForm').hidden=true;$('authorInput').value='';$('addAuthor').setAttribute('aria-expanded','false');
 const favoriteButton=$('itemFavorite'),previousItem=favoriteButton.dataset.item,previousPressed=favoriteButton.getAttribute('aria-pressed');favoriteButton.innerHTML=icon('heart');favoriteButton.dataset.item=item.drive_id;favoriteButton.setAttribute('aria-pressed',String(!!item.es_favorito));favoriteButton.setAttribute('aria-label',item.es_favorito?'Quitar de favoritos':'Marcar como favorito');favoriteButton.title=favoriteButton.getAttribute('aria-label');if(previousItem===item.drive_id&&previousPressed!==null&&previousPressed!==favoriteButton.getAttribute('aria-pressed'))animateControl(favoriteButton,'favorite-toggle');
 stars($('itemRating'),item.rating,n=>saveNow('rating',n===S.selected.rating?0:n));
 const date=item.fecha_agregado?new Date(item.fecha_agregado.replace(' ','T')+'Z').toLocaleDateString('es-PE'): '—';
 $('properties').innerHTML=`<div class="property"><span>Tamaño</span><span>${esc(bytes(item.tamano_bytes))}</span></div><div class="property"><span>Tipo</span><span>${esc(({documento:'Documento',contenedor:'Contenedor',video:'Vídeo',audio:'Audio',imagen:'Imagen',otro:'Otro archivo'})[item.tipo_contenido]||item.tipo_contenido||item.tipo)}</span></div><div class="property"><span>Formato</span><span>${esc(item.formato||'—')}</span></div><div class="property"><span>Contenedor</span>${item.tipo==='curso'?'<span>—</span>':`<button id="containerProperty" class="property-action" title="Asignar a contenedor">${esc(item.container_title||'—')}</button>`}</div><div class="property"><span>Añadido</span><span>${esc(date)}</span></div><div class="property"><span>Páginas / dimensiones</span><span>No disponibles</span></div>`+(item.tipo==='curso'&&!item.container_parent?`<div class="property"><label for="deepSearch">Búsqueda profunda en catálogo general</label><input id="deepSearch" type="checkbox" ${item.indexar_contenido?'checked':''} aria-label="Buscar archivos y carpetas internas desde la biblioteca"></div>`:'')+((item.container_parent||(S.bulkIds.size>1&&S.items.some(i=>S.bulkIds.has(i.drive_id)&&i.container_parent)))?`<div class="property"><label for="searchOverride">Búsqueda global</label><select id="searchOverride" aria-label="Incluir en búsqueda global"><option value="-1" ${item.search_override===-1?'selected':''}>Heredar</option><option value="1" ${item.search_override===1?'selected':''}>Incluir</option><option value="0" ${item.search_override===0?'selected':''}>Excluir</option></select></div><div class="property"><label for="containerFilterProperty">Mostrar en filtros principales</label><input id="containerFilterProperty" type="checkbox" ${item.mostrar_en_filtros===0?'':'checked'} aria-label="Mostrar favorito, calificación y estado al filtrar en el menú principal"></div>`:'')+`<div class="property"><span>Fijado</span><button id="pinProperty" class="property-action" aria-pressed="${!!item.fijado}">${item.fijado?'Quitar':'Fijar'}</button></div>`+`<div class="property"><label for="hiddenProperty">Visible</label><input id="hiddenProperty" type="checkbox" ${item.oculto?'':'checked'} aria-label="Mostrar en biblioteca"></div>`;

}
$('properties').onchange=guard(async event=>{if(!S.selected)return;const id=S.selected.drive_id;if(event.target.id==='deepSearch'){const result=await api('set_deep_search',{id,enabled:event.target.checked});S.selected.indexar_contenido=result.indexar_contenido;await refresh();notify(result.indexar_contenido?'Búsqueda profunda activada':'Búsqueda profunda desactivada');}else if(event.target.id==='hiddenProperty'){const hidden=!event.target.checked,ids=S.bulkIds.size?[...S.bulkIds]:[id];if(ids.length>1)await api('bulk_update',{ids,field:'oculto',value:hidden});else await api('set_hidden',{id,hidden});S.selected.oculto=hidden?1:0;if(S.view==='course')for(const row of S.resources)if(ids.includes(row.id))row.oculto=hidden?1:0;for(const targetId of ids){const card=S.items.find(i=>i.drive_id===targetId);if(card)card.oculto=hidden?1:0;}renderDetail(S.selected);await refresh();if(hidden)notify('Oculto. Busca @ocultos para volver a mostrarlo.');}else if(event.target.id==='containerFilterProperty'){const enabled=event.target.checked,ids=S.bulkIds.size?[...S.bulkIds]:[id];await api('bulk_update',{ids,field:'mostrar_en_filtros',value:enabled});S.selected.mostrar_en_filtros=enabled?1:0;if(S.view==='course')for(const row of S.resources)if(ids.includes(row.id))row.mostrar_en_filtros=enabled?1:0;for(const targetId of ids){const card=S.items.find(i=>i.drive_id===targetId);if(card)card.mostrar_en_filtros=enabled?1:0;}renderDetail(S.selected);await refresh();}else if(event.target.id==='searchOverride'){const value=Number(event.target.value),ids=S.bulkIds.size?[...S.bulkIds]:[id];await api('set_search_override',{ids,value});S.selected.search_override=value;if(S.view==='course')for(const row of S.resources)if(ids.includes(row.id))row.search_override=value;for(const targetId of ids){const card=S.items.find(i=>i.drive_id===targetId);if(card)card.search_override=value;}renderDetail(S.selected);await refresh();}});
$('properties').addEventListener('click',guard(async event=>{if(event.target.id!=='pinProperty'||!S.selected)return;const value=!S.selected.fijado;await api('bulk_update',{ids:S.bulkIds.size?[...S.bulkIds]:[S.selected.drive_id],field:'fijado',value});S.selected.fijado=Number(value);renderDetail(S.selected);await refresh();}));
$('properties').onclick=guard(async event=>{const anchor=event.target.closest('#containerProperty');if(!anchor||!S.selected)return;const el=pop(anchor);if(!el)return;el.classList.add('container-popover');const containers=await api('containers');el.innerHTML='<input id="containerSearch" type="search" placeholder="Buscar contenedor…" aria-label="Nombre del contenedor"><div id="containerOptions"></div>';const input=el.querySelector('#containerSearch'),options=el.querySelector('#containerOptions');const render=()=>{const needle=foldText(input.value.trim());options.innerHTML=containers.filter(c=>foldText(c.titulo).includes(needle)).map(c=>`<button data-container-id="${esc(c.drive_id)}">${icon('package')} ${esc(c.titulo)}</button>`).join('')+(input.value.trim()&&!containers.some(c=>foldText(c.titulo)===needle)?`<button data-create-container="true">+ Crear “${esc(input.value.trim())}”</button>`:'');};const center=()=>{el.style.left=Math.max(12,(innerWidth-el.offsetWidth)/2)+'px';el.style.right='auto';el.style.top=Math.max(12,(innerHeight-el.offsetHeight)/2)+'px';};const assign=async(containerId,name)=>{const ids=S.bulkIds.size?[...S.bulkIds]:[S.selected.drive_id];el.hidden=true;notify(name?'Creando contenedor en Drive…':'Moviendo archivos al contenedor…','working',true);let result;try{result=await api('assign_container',{ids,container_id:containerId,name});}catch(error){notify(error.message,'error');throw error;}S.bulkIds.clear();S.selected=null;$('details').hidden=true;$('inspectorEmpty').hidden=false;el.hidden=true;await refresh();notify(name?`Contenedor creado · ${result.moved} archivo(s) añadidos`:`${result.moved} archivo(s) movidos al contenedor`,'success');};input.oninput=render;input.onkeydown=guard(async e=>{if(e.key!=='Enter')return;e.preventDefault();const value=input.value.trim();if(!value)return;const existing=containers.find(c=>foldText(c.titulo)===foldText(value));await assign(existing?.drive_id||null,existing?null:value);});options.onclick=guard(async e=>{const existing=e.target.closest('[data-container-id]'),create=e.target.closest('[data-create-container]');if(existing)await assign(existing.dataset.containerId,null);else if(create)await assign(null,input.value.trim());});render();center();input.focus();});
function queueSave(field,value){if(!S.selected)return;const id=S.selected.drive_id,key=id+':'+field,previous=S.pending.get(key);if(previous)clearTimeout(previous.timer);const change={id,field,value};change.timer=setTimeout(()=>guard(()=>flush())(),500);S.pending.set(key,change);$('saveState').textContent='Guardando…';}
async function flush(){const edits=[...S.pending.entries()];for(const [,edit]of edits)clearTimeout(edit.timer);for(const [key]of edits)S.pending.delete(key);if(!edits.length)return S.saving;
 const work=async()=>{for(const [key,edit]of edits){try{const item=await api('update',edit);if(S.selected?.drive_id===edit.id){S.selected={...S.selected,[edit.field]:item[edit.field]};$('saveState').textContent='Guardado';}const card=S.items.find(i=>i.drive_id===edit.id);if(card)Object.assign(card,{[edit.field]:item[edit.field]});}catch(e){for(const [pendingKey,pendingEdit] of edits.slice(edits.findIndex(([k])=>k===key)))if(!S.pending.has(pendingKey))S.pending.set(pendingKey,pendingEdit);$('saveState').textContent='Sin guardar';throw e;}}};S.saving=S.saving.catch(()=>{}).then(work);await S.saving;}
async function saveNow(field,value){if(S.bulkIds.size>1&&['rating','es_favorito','estado_lectura','idioma'].includes(field)){
  await flush();await api('bulk_update',{ids:[...S.bulkIds],field,value});
  if(S.selected)S.selected[field]=value;
  if(S.view==='course')for(const row of S.resources)if(S.bulkIds.has(row.id))row[field]=value;
  for(const id of S.bulkIds){const card=S.items.find(i=>i.drive_id===id);if(card)card[field]=value;}
  if(S.selected)renderDetail(S.selected);await refresh();return;}
  queueSave(field,value);await flush();if(field==='etiquetas'){tagCatalog=null;if(S.selected)S.selected=await api('detail',{id:S.selected.drive_id});}if(field==='autor')authorCatalog=null;if(S.selected)renderDetail(S.selected);await refresh();}
$('title').oninput=()=>{resizeDetailTitle();queueSave('titulo',$('title').value);};$('notes').oninput=()=>queueSave('notas',$('notes').value);
for(const id of ['title','notes'])$(id).onblur=guard(async()=>{await flush();await refresh();});
$('readingState').onchange=guard(()=>{animateControl($('readingState'),'state-change');return saveNow('estado_lectura',$('readingState').value);});
$('itemLanguage').onchange=guard(()=>{return saveNow('idioma',$('itemLanguage').value);});

$('languagesDialogClose').onclick=()=>$('languagesDialog').close();
$('languagesForm').onsubmit=guard(async e=>{
 e.preventDefault();
 const name=$('languageInput').value.trim();
 if(!name)return;
 const res=await api('add_language',{name});
 S.languages=res.languages;
 renderLanguagesList();
 $('languageInput').value='';
 if(S.selected)populateLanguageSelect(S.selected.idioma||'',S.bulkIds.size>1);
 notify(`Idioma "${name}" añadido`,'success');
});
$('languagesList').onclick=guard(async e=>{
 const btn=e.target.closest('[data-del-lang]');
 if(!btn)return;
 const name=btn.dataset.delLang;
 const res=await api('delete_language',{name});
 S.languages=res.languages;
 renderLanguagesList();
 if(S.selected)populateLanguageSelect(S.selected.idioma||'',S.bulkIds.size>1);
 notify(`Idioma "${name}" eliminado`);
});

$('itemFavorite').onclick=guard(()=>saveNow('es_favorito',S.selected.es_favorito?0:1));
$('itemAuthors').onclick=guard(async event=>{const remove=event.target.closest('[data-author-remove]');if(!remove||!S.selected)return;const names=authorNames(S.selected.autor);if(S.bulkIds.size>1){await bulkMetadata('autor','remove',names[Number(remove.dataset.authorRemove)]);return;}names.splice(Number(remove.dataset.authorRemove),1);await saveNow('autor',names.join('\n'));$('addAuthor')?.focus();});
$('authorForm').onsubmit=guard(async event=>{event.preventDefault();if(!S.selected)return;const name=$('authorInput').value.trim().replace(/\s+/g,' ');if(!name)return;if(S.bulkIds.size>1){await bulkMetadata('autor','add',name);$('authorInput').value='';return;}const names=authorNames(S.selected.autor);if(!names.some(existing=>existing.toLocaleLowerCase()===name.toLocaleLowerCase())){names.push(name);await saveNow('autor',names.join('\n'));$('addAuthor')?.focus();}else{$('authorInput').select();}});
$('itemTags').onclick=guard(e=>{if(suppressTagClick)return;const tag=e.target.closest('[data-tag]')?.dataset.tag;if(tag)return addToken(tag);});$('itemTags').oncontextmenu=guard(async e=>{const tag=e.target.closest('[data-tag]')?.dataset.tag;if(tag){e.preventDefault();if(S.bulkIds.size>1)await bulkMetadata('etiquetas','remove',tag);else await saveNow('etiquetas',S.selected.etiquetas.split(/\s+/).filter(t=>t!==tag).join(' '));}});
let draggedTagIndex=null;
let tagPointer=null,suppressTagClick=false;
$('itemTags').onpointerdown=e=>{if(e.pointerType==='mouse'||S.bulkIds.size>1||S.selected?.container_parent)return;const tag=e.target.closest('[data-tag-index]');if(!tag)return;tagPointer={from:Number(tag.dataset.tagIndex),to:Number(tag.dataset.tagIndex),x:e.clientX,y:e.clientY,dragging:false};$('itemTags').setPointerCapture(e.pointerId);};
$('itemTags').onpointermove=e=>{if(!tagPointer)return;if(!tagPointer.dragging&&Math.hypot(e.clientX-tagPointer.x,e.clientY-tagPointer.y)<8)return;tagPointer.dragging=true;e.preventDefault();$('itemTags').querySelectorAll('.drop-target').forEach(node=>node.classList.remove('drop-target'));const target=document.elementFromPoint(e.clientX,e.clientY)?.closest('[data-tag-index]');if(target&&$('itemTags').contains(target)){target.classList.add('drop-target');tagPointer.to=Number(target.dataset.tagIndex);}};
$('itemTags').onpointerup=guard(async e=>{if(!tagPointer)return;const drag=tagPointer;tagPointer=null;$('itemTags').querySelectorAll('.drop-target').forEach(node=>node.classList.remove('drop-target'));if(!drag.dragging)return;suppressTagClick=true;setTimeout(()=>suppressTagClick=false,250);if(drag.from===drag.to)return;const tags=String(S.selected.etiquetas||'').split(/\s+/).filter(Boolean);const [tag]=tags.splice(drag.from,1);tags.splice(drag.to,0,tag);await saveNow('etiquetas',tags.join(' '));});
$('itemTags').onpointercancel=()=>{tagPointer=null;$('itemTags').querySelectorAll('.drop-target').forEach(node=>node.classList.remove('drop-target'));};
$('itemTags').ondragstart=e=>{if(S.bulkIds.size>1||S.selected?.container_parent)return;const tag=e.target.closest('[data-tag-index]');if(!tag)return;draggedTagIndex=Number(tag.dataset.tagIndex);tag.classList.add('dragging');e.dataTransfer.effectAllowed='move';};
$('itemTags').ondragover=e=>{const tag=e.target.closest('[data-tag-index]');if(draggedTagIndex===null||!tag)return;e.preventDefault();tag.classList.add('drop-target');};
$('itemTags').ondragleave=e=>{e.target.closest('[data-tag-index]')?.classList.remove('drop-target');};
$('itemTags').ondrop=guard(async e=>{const target=e.target.closest('[data-tag-index]');if(draggedTagIndex===null||!target)return;e.preventDefault();const to=Number(target.dataset.tagIndex),tags=String(S.selected.etiquetas||'').split(/\s+/).filter(Boolean);if(to!==draggedTagIndex){const [tag]=tags.splice(draggedTagIndex,1);tags.splice(to,0,tag);await saveNow('etiquetas',tags.join(' '));}draggedTagIndex=null;});
$('itemTags').ondragend=()=>{draggedTagIndex=null;$('itemTags').querySelectorAll('.dragging,.drop-target').forEach(node=>node.classList.remove('dragging','drop-target'));};
$('tagForm').onsubmit=guard(async e=>{e.preventDefault();const text=$('tagInput').value.trim();if(text){recordRecentTag(text);tagCatalog=null;if(S.bulkIds.size>1)await bulkMetadata('etiquetas','add',text);else await saveNow('etiquetas',S.selected.etiquetas+' '+text);$('tagInput').value='';}});
$('driveOpen').onclick=guard(async()=>{await flush();const result=await api('open',{id:S.selected.drive_id,mode:'web'});if(!result)throw Error('No se pudo abrir Google Drive.');await refresh(true);});
$('localOpen').onclick=guard(async()=>{await flush();await api('reveal',{id:S.selected.drive_id});});

let coverEditorState={item:null,targetIds:[],containerId:null,img:null,scale:1,minScale:1,panX:0,panY:0,rotation:0,hasExistingCover:false,isDragging:false,startX:0,startY:0,startPanX:0,startPanY:0};
function initCoverEditorImage(img){
 const fillScale=Math.max(600/img.naturalWidth,800/img.naturalHeight);
 coverEditorState.minScale=Math.min(600/img.naturalWidth,800/img.naturalHeight);
 coverEditorState.scale=fillScale;
 coverEditorState.panX=0;coverEditorState.panY=0;coverEditorState.rotation=0;
 const slider=$('coverZoomSlider');
 const minVal=Math.max(0.1,coverEditorState.minScale*0.75),maxVal=Math.max(2.5,fillScale*4);
 slider.min=String(minVal);slider.max=String(maxVal);slider.step=String((maxVal-minVal)/200);
 slider.value=String(fillScale);
 renderCoverEditor();
}
function renderCoverEditor(){
 const canvas=$('coverCropCanvas');if(!canvas)return;
 const ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);
 if(!coverEditorState.img){
  $('coverCropEmpty').hidden=false;$('coverCropCanvas').hidden=true;
  $('coverSaveBtn').disabled=true;$('coverDeleteBtn').disabled=!coverEditorState.hasExistingCover;
  return;
 }
 $('coverCropEmpty').hidden=true;$('coverCropCanvas').hidden=false;
 $('coverSaveBtn').disabled=false;$('coverDeleteBtn').disabled=!coverEditorState.hasExistingCover;
 ctx.save();
 ctx.translate(canvas.width/2,canvas.height/2);
 ctx.translate(coverEditorState.panX,coverEditorState.panY);
 ctx.rotate((coverEditorState.rotation*Math.PI)/180);
 ctx.scale(coverEditorState.scale,coverEditorState.scale);
 const img=coverEditorState.img;
 ctx.drawImage(img,-img.naturalWidth/2,-img.naturalHeight/2);
 ctx.restore();
}
async function openCoverDialog(item,containerId=null,ids=[]){
 if(!item&&(!ids||!ids.length))return;
 const dialog=$('coverDialog');if(!dialog)return;
 const targetIds=(ids&&ids.length)?ids:(item?[item.drive_id||item.id]:[]);
 const count=targetIds.length;
 coverEditorState={item,targetIds,containerId,img:null,scale:1,minScale:1,panX:0,panY:0,rotation:0,hasExistingCover:count>1,isDragging:false,startX:0,startY:0,startPanX:0,startPanY:0};
 const badge=$('coverDialogBadge');
 if(count>1){
  if(badge){badge.textContent=String(count);badge.hidden=false;}
  $('coverDialogTitle').textContent='Opciones de portadas';
  $('coverDialogSubtitle').textContent=`${count} elementos seleccionados`;
  const changeSpan=$('coverChangeBtn')?.querySelector('span');if(changeSpan)changeSpan.textContent='Cambiar portadas…';
  const emptyUpload=$('coverUploadBtnEmpty');if(emptyUpload)emptyUpload.textContent='Cargar portadas';
  const deleteSpan=$('coverDeleteBtn')?.querySelector('span');if(deleteSpan)deleteSpan.textContent='Eliminar portadas';
  if($('coverSaveBtn'))$('coverSaveBtn').textContent='Guardar portadas';
 }else{
  if(badge)badge.hidden=true;
  $('coverDialogTitle').textContent='Opciones de portada';
  $('coverDialogSubtitle').textContent=item?.titulo||item?.title||item?.name||'';
  const changeSpan=$('coverChangeBtn')?.querySelector('span');if(changeSpan)changeSpan.textContent='Cambiar portada…';
  const emptyUpload=$('coverUploadBtnEmpty');if(emptyUpload)emptyUpload.textContent='Cargar portada';
  const deleteSpan=$('coverDeleteBtn')?.querySelector('span');if(deleteSpan)deleteSpan.textContent='Eliminar portada';
  if($('coverSaveBtn'))$('coverSaveBtn').textContent='Guardar portada';
 }
 $('coverCropEmpty').hidden=true;$('coverCropCanvas').hidden=false;
 $('coverSaveBtn').disabled=true;$('coverDeleteBtn').disabled=!coverEditorState.hasExistingCover;
 const id=item?.drive_id||item?.id||targetIds[0];
 let currentSrc=coverCache.get(id);
 if(!currentSrc){
  try{
   if(containerId)currentSrc=await api('container_cover',{container:containerId,id});
   else currentSrc=await api('cover',{id});
  }catch{currentSrc=null;}
 }
 if(currentSrc){
  coverEditorState.hasExistingCover=true;
  $('coverDeleteBtn').disabled=false;
  const img=new Image();img.crossOrigin='anonymous';
  img.onload=()=>{coverEditorState.img=img;initCoverEditorImage(img);};
  img.onerror=()=>{coverEditorState.img=null;renderCoverEditor();};
  img.src=currentSrc;
 }else{coverEditorState.img=null;renderCoverEditor();}
 dialog.showModal();
}
const cropVp=$('coverCropViewport');
if(cropVp){
 cropVp.addEventListener('pointerdown',e=>{
  if(e.button!==0||!coverEditorState.img)return;
  coverEditorState.isDragging=true;coverEditorState.startX=e.clientX;coverEditorState.startY=e.clientY;
  coverEditorState.startPanX=coverEditorState.panX;coverEditorState.startPanY=coverEditorState.panY;
  cropVp.classList.add('is-dragging');cropVp.setPointerCapture(e.pointerId);
 });
 cropVp.addEventListener('pointermove',e=>{
  if(!coverEditorState.isDragging||!coverEditorState.img)return;
  const canvas=$('coverCropCanvas'),rect=canvas.getBoundingClientRect();
  const scaleX=canvas.width/rect.width,scaleY=canvas.height/rect.height;
  coverEditorState.panX=coverEditorState.startPanX+(e.clientX-coverEditorState.startX)*scaleX;
  coverEditorState.panY=coverEditorState.startPanY+(e.clientY-coverEditorState.startY)*scaleY;
  renderCoverEditor();
 });
 const stopCropDrag=()=>{if(coverEditorState.isDragging){coverEditorState.isDragging=false;cropVp.classList.remove('is-dragging');}};
 cropVp.addEventListener('pointerup',stopCropDrag);
 cropVp.addEventListener('pointercancel',stopCropDrag);
 cropVp.addEventListener('wheel',e=>{
  if(!coverEditorState.img)return;e.preventDefault();
  const factor=e.deltaY<0?1.08:.92,slider=$('coverZoomSlider');
  const minVal=Number(slider.min)||0.1,maxVal=Number(slider.max)||4;
  coverEditorState.scale=Math.max(minVal,Math.min(maxVal,coverEditorState.scale*factor));
  slider.value=String(coverEditorState.scale);
  renderCoverEditor();
 },{passive:false});
}
$('coverZoomSlider')?.addEventListener('input',e=>{if(!coverEditorState.img)return;coverEditorState.scale=Number(e.target.value);renderCoverEditor();});
$('coverZoomIn')?.addEventListener('click',()=>{if(!coverEditorState.img)return;const slider=$('coverZoomSlider'),maxVal=Number(slider.max)||4;coverEditorState.scale=Math.min(maxVal,coverEditorState.scale*1.15);slider.value=String(coverEditorState.scale);renderCoverEditor();});
$('coverZoomOut')?.addEventListener('click',()=>{if(!coverEditorState.img)return;const slider=$('coverZoomSlider'),minVal=Number(slider.min)||0.1;coverEditorState.scale=Math.max(minVal,coverEditorState.scale/1.15);slider.value=String(coverEditorState.scale);renderCoverEditor();});
$('coverCenterBtn')?.addEventListener('click',()=>{if(!coverEditorState.img)return;coverEditorState.panX=0;coverEditorState.panY=0;renderCoverEditor();});
$('coverFitBtn')?.addEventListener('click',()=>{if(!coverEditorState.img)return;coverEditorState.panX=0;coverEditorState.panY=0;coverEditorState.scale=Math.min(600/coverEditorState.img.naturalWidth,800/coverEditorState.img.naturalHeight);$('coverZoomSlider').value=String(coverEditorState.scale);renderCoverEditor();});
$('coverFillBtn')?.addEventListener('click',()=>{if(!coverEditorState.img)return;coverEditorState.panX=0;coverEditorState.panY=0;coverEditorState.scale=Math.max(600/coverEditorState.img.naturalWidth,800/coverEditorState.img.naturalHeight);$('coverZoomSlider').value=String(coverEditorState.scale);renderCoverEditor();});
$('coverRotateBtn')?.addEventListener('click',()=>{if(!coverEditorState.img)return;coverEditorState.rotation=(coverEditorState.rotation+90)%360;renderCoverEditor();});
function pickCoverDialogFile(){$('coverDialogFileInput').click();}
$('coverChangeBtn')?.addEventListener('click',pickCoverDialogFile);
$('coverUploadBtnEmpty')?.addEventListener('click',pickCoverDialogFile);
$('coverDialogFileInput')?.addEventListener('change',guard(async e=>{
 const file=e.target.files?.[0];e.target.value='';if(!file)return;
 if(!['image/jpeg','image/png','image/webp'].includes(file.type))throw Error('Selecciona una imagen JPG, PNG o WEBP.');
 if(file.size>12_000_000)throw Error('La portada debe pesar menos de 12 MB.');
 const dataUrl=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsDataURL(file);});
 const img=new Image();img.onload=()=>{coverEditorState.img=img;initCoverEditorImage(img);};img.src=dataUrl;
}));
$('coverDeleteBtn')?.addEventListener('click',guard(async()=>{
 const ids=coverEditorState.targetIds.length?coverEditorState.targetIds:(coverEditorState.item?.drive_id?[coverEditorState.item.drive_id]:[]);
 if(!ids.length)return;
 for(const id of ids){
  await api('delete_cover',{id,container:coverEditorState.containerId});
  coverCache.delete(id);S.covers.delete(id);
  const card=S.rows.get(id);
  if(card){card.querySelector('.cover img')?.remove();const t=card.querySelector('.typography');if(t)t.hidden=false;}
  if(S.selected?.drive_id===id){$('hero').querySelector('img')?.remove();$('heroArt').hidden=false;}
  if(S.view==='course'){const rCard=$('resources').querySelector(`[data-id="${CSS.escape(id)}"]`);if(rCard)rCard.querySelector('.resource-cover img')?.remove();}
 }
 $('coverDialog').close();notify(ids.length>1?`${ids.length} portadas eliminadas`:'Portada eliminada');scheduleDraw();
}));
$('coverSaveBtn')?.addEventListener('click',guard(async()=>{
 const ids=coverEditorState.targetIds.length?coverEditorState.targetIds:(coverEditorState.item?.drive_id?[coverEditorState.item.drive_id]:[]);
 if(!ids.length||!coverEditorState.img)return;
 renderCoverEditor();
 const canvas=$('coverCropCanvas');
 const dataUrl=canvas.toDataURL('image/jpeg',0.84);
 const data=dataUrl.split(',')[1];
 for(const id of ids){
  await api('save_cover',{id,data,container:coverEditorState.containerId});
  coverCache.set(id,dataUrl);S.covers.delete(id);
  const card=S.rows.get(id);
  if(card){
   let img=card.querySelector('.cover img');
   if(!img){img=new Image();img.alt='';img.decoding='async';card.querySelector('.cover').prepend(img);}
   img.src=dataUrl;const t=card.querySelector('.typography');if(t)t.hidden=true;
  }
  if(S.selected?.drive_id===id){
   let img=$('hero').querySelector('img');
   if(!img){img=new Image();img.alt='';$('hero').prepend(img);}
   img.src=dataUrl;$('heroArt').hidden=true;
  }
  if(S.view==='course'){
   const rCard=$('resources').querySelector(`[data-id="${CSS.escape(id)}"]`);
   if(rCard){
    let img=rCard.querySelector('.resource-cover img');
    if(!img){img=new Image();img.alt='';rCard.querySelector('.resource-cover')?.prepend(img);rCard.querySelector('.resource-art')?.remove();}
    img.src=dataUrl;
   }
  }
 }
 $('coverDialog').close();notify(ids.length>1?`${ids.length} portadas actualizadas`:'Portada actualizada');scheduleDraw();
}));
$('coverCancelBtn')?.addEventListener('click',()=>$('coverDialog').close());
$('coverDialogClose')?.addEventListener('click',()=>$('coverDialog').close());
$('coverDialog')?.addEventListener('click',e=>{if(e.target===$('coverDialog'))$('coverDialog').close();});

async function importCover(file){if(!file||!S.selected)return;if(!['image/jpeg','image/png','image/webp'].includes(file.type))throw Error('Selecciona una imagen JPG, PNG o WEBP.');if(file.size>12_000_000)throw Error('La portada debe pesar menos de 12 MB.');const id=S.selected.drive_id;const data=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result.split(',')[1]);r.onerror=reject;r.readAsDataURL(file);});await api('save_cover',{id,data});S.covers.delete(id);coverCache.delete(id);if(S.selected?.drive_id===id)renderDetail(S.selected);S.rows.get(id)?.remove();S.rows.delete(id);scheduleDraw();notify('Portada actualizada');}
$('hero').ondblclick=guard(()=>S.selected&&openItem(S.selected));$('hero').onkeydown=guard(e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();if(S.selected)return openItem(S.selected);}if(e.key==='F2'){e.preventDefault();if(S.selected){const ids=S.bulkIds.size>1?[...S.bulkIds]:[S.selected.drive_id];openCoverDialog(S.selected,null,ids);}}});$('hero').oncontextmenu=e=>{e.preventDefault();if(S.selected){const ids=S.bulkIds.size>1?[...S.bulkIds]:[S.selected.drive_id];openCoverDialog(S.selected,null,ids);}};$('coverFile').onchange=guard(async e=>{const file=e.target.files[0];e.target.value='';await importCover(file);});$('hero').ondragover=e=>{e.preventDefault();$('hero').classList.add('dragging');};$('hero').ondragleave=()=>$('hero').classList.remove('dragging');$('hero').ondrop=guard(async e=>{e.preventDefault();$('hero').classList.remove('dragging');await importCover(e.dataTransfer.files[0]);});
document.addEventListener('dragover',e=>e.preventDefault());document.addEventListener('drop',guard(async e=>{e.preventDefault();if(e.target.closest('#hero')||window.balisco?.nativeDrop)return;const file=[...(e.dataTransfer?.files||[])][0];const path=file?.pywebviewFullPath||file?.path;if(!path){notify('Suelta archivos desde el Explorador de Windows.','error');return;}const job=await api('start_import',{path});window.balisco?.importStarted(job.name,job.kind,job.id);}));
function courseLayoutKey(path=S.coursePath){const relative=path.map(part=>part.toLocaleLowerCase()).join('/'),folderId=S.courseFolderIds.get(relative);return 'balisco.containerLayout.v1.'+S.course.drive_id+'.'+(path.length?(folderId?'id:'+folderId:'path:'+JSON.stringify(path.map(part=>part.toLocaleLowerCase()))):'root');}
function saveCourseLayout(){if(!S.course)return;localStorage.setItem(courseLayoutKey(),JSON.stringify({view:S.courseViewMode,grid:S.courseZoom.grid,list:S.courseZoom.list}));}
function loadCourseLayout(path,preferredView=null){let saved=null;try{saved=JSON.parse(localStorage.getItem(courseLayoutKey(path))||'null');}catch{}if(Number.isInteger(saved?.grid)&&saved.grid>=0&&saved.grid<=3)S.courseZoom.grid=saved.grid;if(Number.isInteger(saved?.list)&&saved.list>=0&&saved.list<=4)S.courseZoom.list=saved.list;S.courseViewMode=['grid','list','details'].includes(saved?.view)?saved.view:preferredView||S.courseViewMode;}
function navigateCoursePath(path){saveCourseLayout();S.coursePath=[...path];loadCourseLayout(S.coursePath);clearCourseSelection();renderResources();}
async function openItem(item){
 await flush();
 if(item.tipo!=='curso'&&!item.container_parent){if(!await api('open',{id:item.drive_id,mode:S.mode}))throw Error('No se pudo abrir el elemento.');await refresh(true);return;}
 const root=item.container_parent?await api('detail',{id:item.container_parent}):item;
 S.course=root;S.coursePath=[];S.courseFolderIds=new Map();S.courseZoom={grid:0,list:1};S.courseQuery='';S.courseSelection=null;S.courseSelectedKeys.clear();S.courseSelectionRevision++;S.courseCovers.clear();
 const modern=localStorage.getItem('balisco.containerView.v2.'+root.drive_id),legacy=localStorage.getItem('balisco.containerView.'+root.drive_id);
 S.courseViewMode=modern||(legacy==='grid'?'grid':'details');loadCourseLayout([]);setView('course');$('courseView').dataset.layout=S.courseViewMode;updateCourseViewButton();
 $('summary').textContent='…';$('resources').innerHTML='<div class="library-loader" role="status" aria-label="Cargando contenido"><div class="loading-dots" aria-hidden="true"><span></span><span></span><span></span></div></div>';
 const [view,resources]=await Promise.all([api('container_view',{id:root.drive_id}),api('container',{id:root.drive_id})]);
 if(S.course?.drive_id!==root.drive_id)return;
 loadCourseLayout([],['grid','list','details'].includes(view.view)?view.view:'details');localStorage.setItem('balisco.containerView.v2.'+root.drive_id,S.courseViewMode);
 S.resources=resources;S.courseFolderIds=new Map(resources.filter(row=>row.folder&&row.id).map(row=>[resourceParts(row).map(part=>part.toLocaleLowerCase()).join('/'),row.id]));
 const target=item.container_parent?resources.find(row=>row.id===item.drive_id):null;
 if(target){const parts=resourceParts(target);navigateCoursePath(target.folder?parts:parts.slice(0,-1));}else renderResources();
 if(target){const key=target.folder?'folder:'+target.title.replaceAll('\\','/'):'file:'+item.drive_id;const row=[...$('resources').querySelectorAll('[data-resource-key]')].find(el=>el.dataset.id===item.drive_id||el.dataset.resourceKey===key);if(row){S.courseSelectedKeys=new Set([row.dataset.resourceKey]);paintCourseSelection();await selectCourseResource(row);row.scrollIntoView({block:'nearest'});}}
}
function resourceParts(resource){return String(resource.title||'').split(/[\\/]+/).map(part=>part.trim()).filter(Boolean);}
function updateCourseGridColumns(){const resources=$('resources'),view=$('courseView'),width=resources.clientWidth||view.clientWidth-48,maxCardWidth=[260,190,150,115][S.courseZoom.grid],columns=Math.max(1,Math.min(8,Math.ceil((width+20)/(maxCardWidth+20))));view.style.setProperty('--course-columns',columns);const listWidth=[330,390,450,520,600][S.courseZoom.list],listColumns=Math.max(1,Math.min(4,Math.floor((width+12)/(listWidth+12)))),count=S.courseVisibleCount||0;view.style.setProperty('--course-list-columns',listColumns);view.style.setProperty('--course-list-rows',Math.max(1,Math.ceil(count/listColumns)));}
new ResizeObserver(updateCourseGridColumns).observe($('courseView'));
function updateCourseViewButton(){const button=$('courseViewToggle'),mode=S.courseViewMode,next={grid:'list',list:'details',details:'grid'}[mode];if(mode==='grid'){if(!button.querySelector('.course-grid-levels'))button.innerHTML='<svg class="course-grid-levels" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>';button.querySelectorAll('.course-grid-levels rect').forEach((square,index)=>square.classList.toggle('is-filled',index<=S.courseZoom.grid));}else button.innerHTML=icon(mode);button.title=`Vista ${mode==='grid'?'Tarjetas':mode==='list'?'Lista':'Detalles'}${mode==='grid'?' · nivel '+(S.courseZoom.grid+1)+' de 4':''} · cambiar a ${next==='grid'?'Tarjetas':next==='list'?'Lista':'Detalles'}`;button.setAttribute('aria-label',button.title);button.setAttribute('aria-pressed',String(mode!=='details'));const slider=$('courseZoom');slider.hidden=mode==='details';if(!slider.hidden){slider.max=mode==='grid'?'3':'4';slider.value=S.courseZoom[mode];slider.setAttribute('aria-valuetext',`Nivel ${Number(slider.value)+1} de ${Number(slider.max)+1}`);}$('courseView').style.setProperty('--course-list-height',[64,72,80,90,104][S.courseZoom.list]+'px');updateCourseGridColumns();}
function animateCourseGridZoom(before){if(!before.size||matchMedia('(prefers-reduced-motion: reduce)').matches)return;for(const card of $('resources').querySelectorAll('.resource-card')){const previous=before.get(card.dataset.resourceKey);if(!previous)continue;const current=card.getBoundingClientRect(),dx=previous.left-current.left,dy=previous.top-current.top,sx=previous.width/current.width,sy=previous.height/current.height;if(Math.abs(dx)+Math.abs(dy)+Math.abs(sx-1)+Math.abs(sy-1)<.01)continue;card.getAnimations().forEach(animation=>animation.cancel());card.animate([{transform:`translate(${dx}px,${dy}px) scale(${sx},${sy})`},{transform:'none'}],{duration:280,easing:'cubic-bezier(.2,.8,.2,1)'});}}
$('courseZoom').oninput=e=>{if(S.courseViewMode==='details')return;const level=Number(e.target.value);if(level===S.courseZoom[S.courseViewMode])return;const before=new Map();let anchor=null;if(S.courseViewMode==='grid'){const viewport=$('courseView').getBoundingClientRect();for(const card of $('resources').querySelectorAll('.resource-card')){const rect=card.getBoundingClientRect();if(rect.bottom>=viewport.top-500&&rect.top<=viewport.bottom+500)before.set(card.dataset.resourceKey,rect);if(!anchor&&rect.bottom>viewport.top+52&&rect.top<viewport.bottom)anchor={card,top:rect.top};}}S.courseZoom[S.courseViewMode]=level;saveCourseLayout();updateCourseViewButton();if(S.courseViewMode==='grid'){if(anchor)$('courseView').scrollTop+=anchor.card.getBoundingClientRect().top-anchor.top;animateCourseGridZoom(before);}};
$('courseZoom').addEventListener('wheel',e=>{e.preventDefault();const slider=$('courseZoom');slider.value=Math.max(0,Math.min(Number(slider.max),Number(slider.value)+(e.deltaY>0?1:-1)));slider.dispatchEvent(new Event('input'));},{passive:false});
document.addEventListener('wheel',e=>{if(!e.ctrlKey||S.view!=='course'||S.courseViewMode==='details'||!e.target.closest('#courseView'))return;e.preventDefault();const slider=$('courseZoom');slider.value=Math.max(0,Math.min(Number(slider.max),Number(slider.value)+(e.deltaY>0?1:-1)));slider.dispatchEvent(new Event('input'));},{passive:false});
const courseCoverObserver=new IntersectionObserver(entries=>{for(const entry of entries){if(!entry.isIntersecting)continue;const card=entry.target;courseCoverObserver.unobserve(card);const id=card.dataset.coverId;if(!id)continue;let task=S.courseCovers.get(id);if(!task){task=api('container_cover',{container:S.course?.drive_id,id}).catch(()=>null);S.courseCovers.set(id,task);}Promise.resolve(task).then(src=>{if(!src||!card.isConnected)return;const image=new Image();image.alt='';image.decoding='async';image.src=src;card.querySelector('.resource-cover')?.prepend(image);card.querySelector('.resource-art')?.remove();});}});
function renderCourseLibraryDetail(item){renderDetail(item,true);const container=$('containerProperty');if(container){container.textContent=S.courseSelection?.location?.split(' / ').slice(0,-1).join(' / ')||S.course?.titulo||'—';container.title='Cambiar de contenedor';}if(S.courseSelectedKeys.size>1){$('bulkNotice').textContent=String(S.courseSelectedKeys.size);$('bulkNotice').hidden=false;}}
function courseMatchRating(rating,expr){const r=Number(rating)||0;expr=expr.trim().toLowerCase();if(expr==='sin'||expr==='0'||expr==='none')return r===0;if(expr.endsWith('+'))return r>=parseInt(expr,10);if(expr.startsWith('>='))return r>=parseInt(expr.slice(2),10);if(expr.startsWith('>'))return r>parseInt(expr.slice(1),10);if(expr.startsWith('<='))return r<=parseInt(expr.slice(2),10);if(expr.startsWith('<'))return r<parseInt(expr.slice(1),10);if(expr.includes('-')){const p=expr.split('-');return r>=parseInt(p[0],10)&&r<=parseInt(p[1],10);}if(expr.includes(','))return expr.split(',').map(s=>parseInt(s.trim(),10)).includes(r);return r===parseInt(expr,10);}
function courseMatchSize(bytes,expr){const size=Number(bytes)||0;expr=expr.trim().toLowerCase();const mult=u=>u==='gb'?1073741824:(u==='mb'?1048576:(u==='kb'?1024:1));const mRange=expr.match(/^(\d+(?:\.\d+)?)\s*(b|kb|mb|gb)?\s*-\s*(\d+(?:\.\d+)?)\s*(b|kb|mb|gb)?$/);if(mRange){const min=parseFloat(mRange[1])*mult(mRange[2]||mRange[4]||'b'),max=parseFloat(mRange[3])*mult(mRange[4]||mRange[2]||'b');return size>=Math.min(min,max)&&size<=Math.max(min,max);}const mCmp=expr.match(/^([<>]=?)?\s*(\d+(?:\.\d+)?)\s*(b|kb|mb|gb)?$/);if(mCmp){const op=mCmp[1]||'>=',val=parseFloat(mCmp[2])*mult(mCmp[3]||'b');if(op==='>')return size>val;if(op==='>=')return size>=val;if(op==='<')return size<val;if(op==='<=')return size<=val;return size>=val;}return true;}
function courseMatches(resource){const terms=[...S.tokens];if(S.courseQuery)terms.push(S.courseQuery);return terms.every(token=>{const text=foldText(token),name=foldText(resource.title+' '+(resource.titulo||'')+' '+(resource.autor||''));if(token==='@favoritos')return !!resource.es_favorito;if(token==='@recientes')return !!resource.ultimo_acceso&&!resource.recent_hidden;if(token==='@ocultos')return !!resource.oculto;if(token.startsWith('@orden:'))return true;if(token.startsWith('@rating:'))return courseMatchRating(resource.rating,token.slice(8));if(token.startsWith('@tipo:')){const types=token.slice(6).toLowerCase().split(',').map(s=>s.trim());return types.includes((resource.tipo_contenido||'otro').toLowerCase());}if(token.startsWith('@formato:')||token.startsWith('@fmt:')){const raw=token.startsWith('@formato:')?token.slice(9):token.slice(5);const fmts=raw.toLowerCase().split(',').map(s=>s.trim().replace(/^\./,''));const ext=((resource.formato||(resource.displayName||resource.title||'').split('.').pop()||'')).toLowerCase();return fmts.includes(ext);}if(token.startsWith('@peso:')||token.startsWith('@tamano:'))return courseMatchSize(resource.size,token.slice(token.indexOf(':')+1));if(token==='@sin:portada'||token==='@sin:miniatura'||token==='@sin:cover')return !resource.has_cover;
if(token==='@con:portada'||token==='@con:miniatura'||token==='@con:cover')return !!resource.has_cover;
if(token.toLowerCase().startsWith('@autor:')||token.toLowerCase().startsWith('@autores:')||token.toLowerCase().startsWith('autor:'))return foldText(resource.autor||'').includes(foldText(token.slice(token.indexOf(':')+1)));if(token.startsWith('@'))return (resource.estado_lectura||'pendiente')===token.slice(1).toLowerCase();return name.includes(text);});}
function courseCompare(a,b){const order=currentSort(),recent=row=>row.ultimo_acceso&&!row.recent_hidden?String(row.ultimo_acceso):'';if(order==='peso')return Number(b.size||0)-Number(a.size||0);if(order==='ligero')return Number(a.size||0)-Number(b.size||0);if(order==='recientes'||order==='abiertos'){const opened=Number(!!recent(b))-Number(!!recent(a));if(opened)return opened;const byAccess=recent(b).localeCompare(recent(a));if(byAccess)return byAccess;}return a.displayName.localeCompare(b.displayName,undefined,{sensitivity:'base'});}
function resourceCardMeta(resource,size,folder){const type=folder?'CONTENEDOR':({documento:'DOCUMENTO',video:'VIDEO',audio:'AUDIO',imagen:'IMAGEN',otro:'ARCHIVO'})[resource?.tipo_contenido]||(resource?.mime?.startsWith('video/')?'VIDEO':resource?.mime?.startsWith('audio/')?'AUDIO':resource?.mime?.startsWith('image/')?'IMAGEN':'DOCUMENTO'),authors=authorNames(resource?.autor);return `<div class="card-meta"><span class="card-type" title="${type}" aria-label="${type}">${type[0]}</span><span class="card-size">${esc(bytes(size))}</span>${resource?.es_favorito?`<span class="favorite-mark" title="Favorito">${icon('heart')}</span>`:''}${resource?.rating?`<span class="card-rating">${icon('star')} ${Number(resource.rating)}</span>`:''}${authors.length?`<span class="card-author" title="${esc(authors.join(', '))}">· ${esc(authors[0])}${authors.length>1?' +'+(authors.length-1):''}</span>`:''}</div>`;}
function renderResources(){
 courseCoverObserver.disconnect();const current=S.coursePath,folders=new Map(),files=[],descendantFolders=new Set(),descendantFiles=new Set(),grid=S.courseViewMode==='grid';$('courseView').dataset.layout=S.courseViewMode;updateCourseViewButton();
 const showHidden=S.tokens.includes('@ocultos');for(const resource of S.resources){if(Boolean(resource.oculto)!==showHidden)continue;const parts=resourceParts(resource);const matches=parts.length>current.length&&current.every((part,index)=>part.toLocaleLowerCase()===parts[index].toLocaleLowerCase());if(!matches)continue;const folderDepth=resource.folder?parts.length:parts.length-1;for(let depth=current.length+1;depth<=folderDepth;depth++)descendantFolders.add(parts.slice(0,depth).join('/').toLocaleLowerCase());if(!resource.folder)descendantFiles.add(resource.id||parts.join('/').toLocaleLowerCase());const rest=parts.slice(current.length),name=rest[0],path=[...current,name].join('/'),key=path.toLocaleLowerCase();if(S.courseQuery||S.tokens.some(t=>!t.startsWith('@orden:'))){if(courseMatches(resource)){if(resource.folder)folders.set(key,{name:rest.join(' / '),path:parts.join('/'),id:resource.id,size:resource.size||0,count:0,mime:resource.mime||''});else files.push({...resource,displayName:rest.join(' / ')});}continue;}if(resource.folder){if(rest.length===1){const folder=folders.get(key)||{name,path,size:0,count:0,mime:resource.mime||''};folder.id=resource.id;folder.mime=resource.mime||folder.mime;folders.set(key,folder);}continue;}if(rest.length===1){files.push({...resource,displayName:rest[0]});continue;}const folder=folders.get(key)||{name,path,size:0,count:0,mime:''};folder.size+=Number(resource.size)||0;folder.count++;folders.set(key,folder);}
 const resourceById=new Map(S.resources.map(resource=>[resource.id,resource]));
 const folderRows=[...folders.values()].sort((a,b)=>a.name.localeCompare(b.name,undefined,{sensitivity:'base'})).map(folder=>{const key='folder:'+folder.path,selected=S.courseSelection?.key===key;return grid?`<div role="button" tabindex="0" class="resource-card folder-card ${selected?'selected':''}" data-resource-key="${esc(key)}" data-folder="${esc(folder.path)}" ${folder.id?`data-id="${esc(folder.id)}"`:''}><div class="resource-cover"><div class="resource-art folder-art">${icon('folder')}<span>CARPETA</span></div></div><div class="resource-card-info"><strong class="resource-card-title" title="${esc(folder.name)}">${esc(folder.name)}</strong>${resourceCardMeta(resourceById.get(folder.id),folder.size,true)}</div></div>`:`<div role="button" tabindex="0" class="resource folder-resource ${selected?'selected':''}" data-resource-key="${esc(key)}" data-folder="${esc(folder.path)}" ${folder.id?`data-id="${esc(folder.id)}"`:''}><span class="resource-name">${icon('folder')}<span title="${esc(folder.name)}">${esc(folder.name)}</span></span><small title="${folder.count} ${folder.count===1?'archivo':'archivos'}">${esc(bytes(folder.size))}</small></div>`;});
 const fileRows=files.sort(courseCompare).map(resource=>{const key='file:'+resource.id,selected=S.courseSelection?.key===key,name=resource.displayName,type=resource.mime?.startsWith('video/')?'video':resource.mime?.startsWith('audio/')?'audio':resource.mime?.startsWith('image/')?'image':'document',format=name.includes('.')?name.split('.').at(-1).toUpperCase():'ARCHIVO';return grid?`<div role="button" tabindex="0" class="resource-card file-card ${selected?'selected':''}" data-resource-key="${esc(key)}" data-id="${esc(resource.id)}" data-cover-id="${esc(resource.id)}"><div class="resource-cover"><div class="resource-art"><div class="resource-format">${esc(format)}</div><strong>${esc(name)}</strong></div></div><div class="resource-card-info"><strong class="resource-card-title" title="${esc(name)}">${esc(name)}</strong>${resourceCardMeta(resource,resource.size,false)}</div></div>`:`<div role="button" tabindex="0" class="resource ${selected?'selected':''}" data-resource-key="${esc(key)}" data-id="${esc(resource.id)}"><span class="resource-name">${icon(type)}<span title="${esc(name)}">${esc(name)}</span></span><small>${bytes(resource.size)}</small></div>`;});
 S.courseVisibleCount=folderRows.length+fileRows.length;$('summary').textContent=String(descendantFolders.size+descendantFiles.size);$('summary').title='Elementos en esta carpeta y sus subcarpetas';$('resources').innerHTML=[...folderRows,...fileRows].join('')||'<p class="resources-empty">No hay resultados en esta carpeta.</p>';$('resources').append(courseMarqueeBox);courseMarqueeBox.hidden=true;
 if(grid){for(const card of $('resources').querySelectorAll('.resource-card')){const resource=resourceById.get(card.dataset.id),state=resource?.estado_lectura||'pendiente';card.dataset.state=state;card.dataset.stateLabel=stateNames[state]||'Pendiente';if(resource?.fijado){card.classList.add('pinned');const pin=document.createElement('span');pin.className='resource-pin';pin.title='Fijado';pin.innerHTML=icon('pin');card.querySelector('.resource-cover')?.append(pin);}}}
 updateCourseGridColumns();
 if(S.courseSelection&&![...$('resources').querySelectorAll('[data-resource-key]')].some(row=>row.dataset.resourceKey===S.courseSelection.key))clearCourseSelection();paintCourseSelection();if(grid)for(const card of $('resources').querySelectorAll('.file-card[data-cover-id]'))courseCoverObserver.observe(card);
 const breadcrumbs=$('courseBreadcrumbs');$('folderBack').hidden=!current.length;breadcrumbs.innerHTML=`<button type="button" class="breadcrumb-root" data-breadcrumb="0" title="${esc(S.course?.titulo||'Contenedor')}">${esc(S.course?.titulo||'Contenedor')}</button>`+current.map((part,index)=>`<span aria-hidden="true">/</span><button type="button" data-breadcrumb="${index+1}" title="${esc(part)}">${esc(part)}</button>`).join('');requestAnimationFrame(()=>{breadcrumbs.scrollLeft=breadcrumbs.scrollWidth;});
 if(S.courseSelection?.detail?.item&&S.selected?.drive_id===S.courseSelection.id){$('courseInspector').hidden=true;renderCourseLibraryDetail(S.selected);}else renderCourseInspector();
}
function renderCourseInspector(animate=true){
 const panel=$('courseInspector'),selection=S.courseSelection;if(S.view!=='course'||!selection){panel.hidden=true;return;}panel.hidden=false;if(animate){animateInspectorSelection();panel.classList.remove('detail-swap');void panel.offsetWidth;panel.classList.add('detail-swap');}
 const detail=selection.detail||{},item=detail.item,title=selection.name||detail.title||'Recurso';
 const properties=[['Tipo',selection.folder?'Carpeta':(detail.mime||selection.mime||'Archivo')],['Tamaño',selection.folder?bytes(selection.size||0):bytes(detail.size??selection.size)],...(selection.folder?[['Contenido',`${selection.count||0} archivos`]]:[])];
 if(item)properties.push(['Formato',item.formato||'—'],['Autor',item.autor||'—']);
 const editable=item?`<div class="field-label">PROPIEDADES PERSONALES</div><div class="property"><span>Favorito</span><button type="button" class="course-favorite ${item.es_favorito?'active':''}" data-course-favorite aria-pressed="${!!item.es_favorito}" aria-label="${item.es_favorito?'Quitar de favoritos':'Marcar como favorito'}">${icon('heart')}</button></div><div class="property"><span>Calificación</span><div class="course-rating" aria-label="Calificación: ${item.rating||0} de 5">${Array.from({length:5},(_,i)=>`<button type="button" data-course-rating="${i+1}" class="${i<item.rating?'on':''}" aria-label="Calificar con ${i+1} estrellas">${icon('star')}</button>`).join('')}</div></div><div class="property"><span>Estado</span><select data-course-state aria-label="Estado de lectura">${states.map(state=>`<option value="${state}" ${item.estado_lectura===state?'selected':''}>${esc(stateNames[state])}</option>`).join('')}</select></div><div class="property"><label for="courseFilterVisible">Mostrar en filtros principales</label><input id="courseFilterVisible" type="checkbox" data-course-filter-visible ${item.mostrar_en_filtros===0?'':'checked'} aria-label="Mostrar favorito, calificación y estado al filtrar en el menú principal"></div><div class="property"><label for="courseVisible">Visible</label><input id="courseVisible" type="checkbox" data-course-visible ${item.oculto?'':'checked'} aria-label="Mostrar en biblioteca"></div>`:'';
 panel.innerHTML=`<div class="course-inspector"><div class="course-hero" data-course-hero>${selection.folder?`<div class="resource-art folder-art">${icon('folder')}<span>CARPETA</span></div>`:`<div class="resource-art"><span class="resource-format">${esc(title.split('.').at(-1).toUpperCase())}</span><strong>${esc(title)}</strong></div>`}${S.courseSelectedKeys.size>1?`<span class="course-multi">${S.courseSelectedKeys.size}</span>`:''}</div>${item?`<textarea class="course-title-input" data-course-field="titulo" rows="2" aria-label="Título">${esc(item.titulo||title)}</textarea>`:`<h2 class="course-title">${esc(title)}</h2>`}<div class="resource-path">${esc(selection.location||'')}</div>${item?`<div class="field-label">NOTAS</div><textarea class="course-notes" data-course-notes placeholder="Ideas, conexiones, algo que recordar…">${esc(item.notas||'')}</textarea><div class="field-label">ETIQUETAS</div><input class="course-text-input" data-course-field="etiquetas" aria-label="Etiquetas" value="${esc(item.etiquetas||'')}"><div class="field-label">AUTORES</div><textarea class="course-text-input" data-course-field="autor" aria-label="Autores" rows="2">${esc(item.autor||'')}</textarea>`:''}<div class="field-label">PROPIEDADES</div>${properties.map(([label,value])=>`<div class="property"><span>${esc(label)}</span><span>${esc(value)}</span></div>`).join('')}${editable}<p class="resource-hint">${selection.folder?'Doble clic para entrar · clic derecho para mover a la biblioteca · Suprimir para borrar la carpeta.':'Doble clic para abrir · clic derecho para mover a la biblioteca · Suprimir para borrar.'}</p></div>`;
 if(!selection.folder&&selection.id){const id=selection.id;let task=S.courseCovers.get(id);if(!task){task=api('container_cover',{container:S.course.drive_id,id}).catch(()=>null);S.courseCovers.set(id,task);}Promise.resolve(task).then(src=>{if(src&&S.courseSelection?.id===id&&panel.isConnected){const hero=panel.querySelector('[data-course-hero]');if(hero){const img=new Image();img.alt='Miniatura';img.src=src;hero.querySelector('.resource-art')?.remove();hero.prepend(img);}}});}
}
async function selectCourseResource(row){const folder=row.hasAttribute('data-folder'),id=row.dataset.id||'',path=folder?row.dataset.folder:'',parts=folder?path.split('/'):[],name=folder?parts.at(-1):(S.resources.find(resource=>resource.id===id)?.title||'').split(/[\\/]+/).at(-1)||'Archivo';const key=row.dataset.resourceKey,resource=S.resources.find(entry=>entry.id===id),selection={key,folder,id,path,name,mime:resource?.mime||'',size:resource?.size||0,location:[S.course?.titulo,...(folder?parts:resourceParts(resource||{}))].filter(Boolean).join(' / '),detail:null,count:0};if(folder){const prefix=path.toLocaleLowerCase()+'/';const descendants=S.resources.filter(entry=>!entry.folder&&entry.title.replaceAll('\\','/').toLocaleLowerCase().startsWith(prefix));selection.count=descendants.length;selection.size=descendants.reduce((sum,entry)=>sum+(Number(entry.size)||0),0);}S.courseSelection=selection;const revision=++S.courseSelectionRevision;for(const entry of $('resources').querySelectorAll('[data-resource-key]'))entry.classList.toggle('selected',entry.dataset.resourceKey===key);$('inspectorEmpty').hidden=true;$('details').hidden=true;renderCourseInspector();if(id){try{selection.detail=await api('container_resource_detail',{container:S.course.drive_id,id});}catch(error){report(error);}}if(revision!==S.courseSelectionRevision)return;if(selection.detail?.item){try{const ids=courseSelectedRows().filter(entry=>entry.dataset.id).map(entry=>entry.dataset.id),[item,indexed]=await Promise.all([api('detail',{id}),api('container_indexed_ids',{container:S.course.drive_id,ids})]);if(revision!==S.courseSelectionRevision)return;S.selected=item;S.bulkIds=new Set(indexed);$('courseInspector').hidden=true;renderCourseLibraryDetail(item);return;}catch(error){report(error);}}S.selected=null;S.bulkIds.clear();$('details').hidden=true;renderCourseInspector(false);}
function paintCourseSelection(){for(const entry of $('resources').querySelectorAll('[data-resource-key]')){const selected=S.courseSelectedKeys.has(entry.dataset.resourceKey);entry.classList.toggle('selected',selected);entry.setAttribute('aria-selected',String(selected));}}
function clearCourseSelection(){S.courseSelection=null;S.courseSelectedKeys.clear();S.courseSelectionRevision++;S.selected=null;S.bulkIds.clear();paintCourseSelection();renderCourseInspector();$('details').hidden=true;$('inspectorEmpty').hidden=false;}
function courseSelectedRows(){return [...$('resources').querySelectorAll('[data-resource-key]')].filter(row=>S.courseSelectedKeys.has(row.dataset.resourceKey));}
async function moveSelectedCourseToStorage(){
 const selected=courseSelectedRows().map(row=>({folder:row.hasAttribute('data-folder'),path:row.dataset.folder||'',id:row.dataset.id||''}));
 const folderPaths=selected.filter(entry=>entry.folder).map(entry=>entry.path.toLocaleLowerCase());
 const actions=selected.filter(entry=>!entry.folder||!folderPaths.some(path=>entry.path.toLocaleLowerCase().startsWith(path+'/')));
 if(!actions.length)return;
 for(const entry of actions){
  if(entry.folder){await api('container_move_folder_to_storage',{container:S.course.drive_id,path:entry.path.split('/')});const prefix=entry.path.toLocaleLowerCase()+'/';S.resources=S.resources.filter(resource=>{const path=resource.title.replaceAll('\\','/').toLocaleLowerCase();return path!==entry.path.toLocaleLowerCase()&&!path.startsWith(prefix);});}
  else if(entry.id){await api('container_move_to_storage',{container:S.course.drive_id,id:entry.id});S.resources=S.resources.filter(resource=>resource.id!==entry.id);}
 }
 clearCourseSelection();renderResources();notify(`${actions.length} ${actions.length===1?'recurso movido':'recursos movidos'} a la biblioteca`);
}
function confirmCourseBulkAction(operation,skipConfirm=false){const rows=courseSelectedRows();if(!rows.length)return;const dialog=$('dialog');$('dialogTitle').textContent=operation==='storage'?'Extraer a la biblioteca':'Eliminar recursos';$('dialogBody').replaceChildren();const message=document.createElement('p');message.textContent=`${rows.length} recursos seleccionados ${operation==='storage'?'se moverán a la biblioteca':'se moverán a la papelera de Drive'}. ¿Continuar?`;const confirm=document.createElement('button');confirm.className=operation==='storage'?'text-button':'text-button danger-button';confirm.textContent=operation==='storage'?'Extraer a la biblioteca':'Mover a la papelera';confirm.onclick=guard(async()=>{const selected=rows.map(row=>({folder:row.hasAttribute('data-folder'),path:row.dataset.folder||'',id:row.dataset.id||''}));const folderPaths=selected.filter(entry=>entry.folder).map(entry=>entry.path.toLocaleLowerCase());const actions=selected.filter(entry=>!entry.folder||!folderPaths.some(path=>entry.path.toLocaleLowerCase().startsWith(path+'/')));for(const entry of actions){if(entry.folder){await api(operation==='storage'?'container_move_folder_to_storage':'container_trash_folder',{container:S.course.drive_id,path:entry.path.split('/')});const prefix=entry.path.toLocaleLowerCase()+'/';S.resources=S.resources.filter(resource=>{const path=resource.title.replaceAll('\\','/').toLocaleLowerCase();return path!==entry.path.toLocaleLowerCase()&&!path.startsWith(prefix);});}else if(entry.id){await api(operation==='storage'?'container_move_to_storage':'container_trash',{container:S.course.drive_id,id:entry.id});S.resources=S.resources.filter(resource=>resource.id!==entry.id);}}clearCourseSelection();renderResources();dialog.close();notify(`${actions.length} recursos actualizados`);});const cancel=document.createElement('button');cancel.className='text-button';cancel.textContent='Cancelar';cancel.onclick=()=>dialog.close();$('dialogBody').append(message,confirm,cancel);if(skipConfirm)confirm.click();else dialog.showModal();}
async function courseSelectFromEvent(row,event){const key=row.dataset.resourceKey,rows=[...$('resources').querySelectorAll('[data-resource-key]')];if(event.shiftKey&&S.courseAnchorKey){const first=rows.findIndex(entry=>entry.dataset.resourceKey===S.courseAnchorKey),last=rows.indexOf(row);if(first>=0){if(!event.ctrlKey)S.courseSelectedKeys.clear();for(let i=Math.min(first,last);i<=Math.max(first,last);i++)S.courseSelectedKeys.add(rows[i].dataset.resourceKey);}}else if(event.ctrlKey||event.metaKey){if(S.courseSelectedKeys.has(key))S.courseSelectedKeys.delete(key);else S.courseSelectedKeys.add(key);S.courseAnchorKey=key;}else{if(S.courseSelectedKeys.size===1&&S.courseSelectedKeys.has(key)){clearCourseSelection();return;}S.courseSelectedKeys=new Set([key]);S.courseAnchorKey=key;}paintCourseSelection();if(!S.courseSelectedKeys.size){clearCourseSelection();return;}const focusKey=S.courseSelectedKeys.has(key)?key:[...S.courseSelectedKeys].at(-1),focusRow=rows.find(entry=>entry.dataset.resourceKey===focusKey);await selectCourseResource(focusRow);paintCourseSelection();}
let courseMarquee=null,courseSuppressClick=false;
const courseMarqueeBox=document.createElement('div');courseMarqueeBox.className='marquee-box';courseMarqueeBox.hidden=true;$('resources').append(courseMarqueeBox);
$('resources').addEventListener('pointerdown',e=>{if(S.courseViewMode!=='grid'||!e.ctrlKey||e.button!==0)return;courseMarquee={x:e.clientX,y:e.clientY,lastX:e.clientX,lastY:e.clientY,pointerId:e.pointerId,base:new Set(S.courseSelectedKeys),dragged:false};});
$('resources').addEventListener('pointermove',e=>{const drag=courseMarquee;if(!drag||drag.pointerId!==e.pointerId)return;drag.lastX=e.clientX;drag.lastY=e.clientY;if(!drag.dragged&&Math.hypot(e.clientX-drag.x,e.clientY-drag.y)>5){drag.dragged=true;$('resources').setPointerCapture(e.pointerId);}if(!drag.dragged)return;const host=$('resources'),rect=host.getBoundingClientRect(),x1=Math.min(drag.x,e.clientX)-rect.left,x2=Math.max(drag.x,e.clientX)-rect.left,y1=Math.min(drag.y,e.clientY)-rect.top,y2=Math.max(drag.y,e.clientY)-rect.top;Object.assign(courseMarqueeBox.style,{left:x1+'px',top:y1+'px',width:x2-x1+'px',height:y2-y1+'px'});courseMarqueeBox.hidden=false;S.courseSelectedKeys=new Set(drag.base);for(const row of host.querySelectorAll('[data-resource-key]')){const r=row.getBoundingClientRect(),left=r.left-rect.left,top=r.top-rect.top;if(left<x2&&left+r.width>x1&&top<y2&&top+r.height>y1)S.courseSelectedKeys.add(row.dataset.resourceKey);}paintCourseSelection();});
$('resources').addEventListener('pointerup',e=>{if(!courseMarquee)return;const dragged=courseMarquee.dragged;courseMarquee=null;courseMarqueeBox.hidden=true;if(dragged){courseSuppressClick=true;const row=courseSelectedRows().at(-1);if(row)guard(async()=>{await selectCourseResource(row);paintCourseSelection();})();setTimeout(()=>{courseSuppressClick=false;},0);}});
$('resources').addEventListener('pointercancel',()=>{courseMarquee=null;courseMarqueeBox.hidden=true;});
$('resources').onclick=guard(async e=>{if(courseSuppressClick)return;const row=e.target.closest('[data-resource-key]');if(!row){if(e.target===$('resources'))clearCourseSelection();return;}const closedMenu=closeRepeatedItemActions(row);if(closedMenu&&S.courseSelectedKeys.has(row.dataset.resourceKey))return;await courseSelectFromEvent(row,e);});
async function updateCourseSelected(field,value){const selection=S.courseSelection,rows=S.courseSelectedKeys.size>1?courseSelectedRows():[...$('resources').querySelectorAll('[data-resource-key]')].filter(row=>row.dataset.resourceKey===selection?.key);let updated=0;for(const row of rows){if(row.hasAttribute('data-folder')||!row.dataset.id)continue;try{await api('container_update',{container:S.course.drive_id,id:row.dataset.id,field,value});updated++;}catch(error){if(rows.length===1)throw error;}}if(selection?.detail?.item){selection.detail.item[field]=['es_favorito','oculto','mostrar_en_filtros'].includes(field)?Number(value):value;renderCourseInspector();}if(rows.length>1)notify(`${updated} archivos actualizados`);}
$('courseInspector').onclick=guard(async e=>{const selection=S.courseSelection,item=selection?.detail?.item;if(!selection||!item)return;if(e.target.closest('[data-course-favorite]')){await updateCourseSelected('es_favorito',!item.es_favorito);return;}const rating=e.target.closest('[data-course-rating]');if(rating)await updateCourseSelected('rating',Number(rating.dataset.courseRating));});
$('courseInspector').onchange=guard(async e=>{const selection=S.courseSelection,item=selection?.detail?.item;if(!selection||!item)return;const field=e.target.matches('[data-course-notes]')?'notas':e.target.dataset.courseField;if(field){await api('update',{id:selection.id,field,value:e.target.value});item[field]=e.target.value;return;}if(e.target.matches('[data-course-state]')){await updateCourseSelected('estado_lectura',e.target.value);return;}if(e.target.matches('[data-course-filter-visible]')){await updateCourseSelected('mostrar_en_filtros',e.target.checked);return;}if(e.target.matches('[data-course-visible]'))await updateCourseSelected('oculto',!e.target.checked);});
$('resources').ondblclick=guard(async e=>{const row=e.target.closest('[data-resource-key]');if(!row)return;if(row.hasAttribute('data-folder')){navigateCoursePath(row.dataset.folder.split('/'));return;}await api('container_open',{container:S.course.drive_id,id:row.dataset.id,mode:S.mode});const resource=S.resources.find(entry=>entry.id===row.dataset.id);if(resource){resource.ultimo_acceso=new Date().toISOString();resource.recent_hidden=0;}});
function confirmCourseAction(selection,operation,skipConfirm=false){const dialog=$('dialog');$('dialogTitle').textContent=operation==='storage'?'Extraer a la biblioteca':selection.folder?'Eliminar carpeta':'Eliminar archivo';$('dialogBody').replaceChildren();const message=document.createElement('p');message.textContent=operation==='storage'?`“${selection.name}” se moverá del contenedor a la biblioteca. ¿Continuar?`:`“${selection.name}” y su contenido se moverán a la papelera de Drive. ¿Continuar?`;const confirm=document.createElement('button');confirm.className=operation==='storage'?'text-button':'text-button danger-button';confirm.textContent=operation==='storage'?'Extraer a la biblioteca':'Mover a la papelera';confirm.onclick=guard(async()=>{if(operation==='storage'&&selection.folder){const result=await api('container_move_folder_to_storage',{container:S.course.drive_id,path:selection.path.split('/')});const prefix=selection.path.toLocaleLowerCase()+'/';S.resources=S.resources.filter(resource=>!resource.title.replaceAll('\\','/').toLocaleLowerCase().startsWith(prefix)&&resource.title.replaceAll('\\','/').toLocaleLowerCase()!==selection.path.toLocaleLowerCase());notify(`${result.moved} archivos movidos a la biblioteca`);}else if(operation==='storage'){await api('container_move_to_storage',{container:S.course.drive_id,id:selection.id});S.resources=S.resources.filter(resource=>resource.id!==selection.id);notify('Elemento movido a la biblioteca');}else if(selection.folder){const parts=selection.path.split('/');await api('container_trash_folder',{container:S.course.drive_id,path:parts});const prefix=selection.path.toLocaleLowerCase()+'/';S.resources=S.resources.filter(resource=>!resource.title.replaceAll('\\','/').toLocaleLowerCase().startsWith(prefix)&&resource.title.replaceAll('\\','/').toLocaleLowerCase()!==selection.path.toLocaleLowerCase());notify('Carpeta movida a la papelera de Drive');}else{await api('container_trash',{container:S.course.drive_id,id:selection.id});S.resources=S.resources.filter(resource=>resource.id!==selection.id);notify('Elemento movido a la papelera de Drive');}S.courseSelection=null;S.courseSelectionRevision++;renderResources();$('courseInspector').hidden=true;$('inspectorEmpty').hidden=false;dialog.close();});const cancel=document.createElement('button');cancel.className='text-button';cancel.textContent='Cancelar';cancel.onclick=()=>dialog.close();$('dialogBody').append(message,confirm,cancel);if(skipConfirm)confirm.click();else dialog.showModal();}
$('resources').oncontextmenu=guard(async e=>{const row=e.target.closest('[data-resource-key]');if(!row)return;e.preventDefault();if(closeRepeatedItemActions(row))return;const point={x:e.clientX,y:e.clientY};if(!S.courseSelectedKeys.has(row.dataset.resourceKey)){S.courseSelectedKeys=new Set([row.dataset.resourceKey]);await selectCourseResource(row);}const ids=courseSelectedRows().map(entry=>entry.dataset.id).filter(Boolean);await openItemActions(row,ids,true,point);});
document.addEventListener('keydown',guard(async e=>{if(S.view!=='course'||e.target.closest('input,textarea,select,[contenteditable]')||$('dialog').open)return;const rows=[...$('resources').querySelectorAll('[data-resource-key]')];if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='a'){e.preventDefault();S.courseSelectedKeys=new Set(rows.map(row=>row.dataset.resourceKey));paintCourseSelection();if(rows[0])await selectCourseResource(rows[0]);paintCourseSelection();return;}if(e.key==='Escape'){clearCourseSelection();return;}if(e.key==='Delete'&&S.courseSelection){e.preventDefault();if(S.courseSelectedKeys.size>1)confirmCourseBulkAction('delete',!S.confirmDelete);else confirmCourseAction(S.courseSelection,'delete',!S.confirmDelete);return;}if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)&&rows.length){e.preventDefault();const current=rows.findIndex(row=>row.dataset.resourceKey===S.courseSelection?.key),columns=S.courseViewMode==='grid'?Math.max(1,Math.round($('resources').clientWidth/(rows[0].getBoundingClientRect().width+20))):S.courseViewMode==='list'?Number(getComputedStyle($('courseView')).getPropertyValue('--course-list-rows'))||1:1,step=S.courseViewMode==='list'?(e.key==='ArrowLeft'?-columns:e.key==='ArrowRight'?columns:e.key==='ArrowUp'?-1:1):(e.key==='ArrowLeft'?-1:e.key==='ArrowRight'?1:e.key==='ArrowUp'?-columns:columns),next=rows[Math.max(0,Math.min(rows.length-1,current+step))];if(next){await courseSelectFromEvent(next,e);next.focus();next.scrollIntoView({block:'nearest'});}return;}if(e.key==='Enter'&&S.courseSelection){e.preventDefault();const row=rows.find(entry=>entry.dataset.resourceKey===S.courseSelection.key);row?.dispatchEvent(new MouseEvent('dblclick',{bubbles:true}));}}));
$('back').innerHTML=icon('back');$('folderBack').innerHTML=icon('back');$('explorer').innerHTML=icon('folder');

$('filters').addEventListener('wheel',e=>{const el=e.currentTarget;if(el.scrollWidth<=el.clientWidth)return;const delta=Math.abs(e.deltaY)>Math.abs(e.deltaX)?e.deltaY:e.deltaX;if(!delta)return;e.preventDefault();el.scrollLeft+=delta;},{passive:false});
$('explorer').onclick=guard(()=>api('container_reveal',{container:S.course.drive_id,path:S.coursePath}));$('courseViewToggle').onclick=guard(async()=>{const previous=S.courseViewMode,view={grid:'list',list:'details',details:'grid'}[previous];S.courseViewMode=view;saveCourseLayout();renderResources();if(S.coursePath.length)return;localStorage.setItem('balisco.containerView.v2.'+S.course.drive_id,view);try{await api('container_view',{id:S.course.drive_id,view});}catch(error){S.courseViewMode=previous;saveCourseLayout();renderResources();throw error;}});$('back').onclick=guard(async()=>{setView('grid');await refresh(true);});$('folderBack').onclick=()=>navigateCoursePath(S.coursePath.slice(0,-1));$('courseBreadcrumbs').onclick=e=>{const crumb=e.target.closest('[data-breadcrumb]');if(crumb)navigateCoursePath(S.coursePath.slice(0,Number(crumb.dataset.breadcrumb)));};$('home')?.addEventListener('click',guard(async()=>{await flush();setView('grid');await refresh();}));
$('courseBreadcrumbs').addEventListener('wheel',e=>{const el=e.currentTarget;if(el.scrollWidth<=el.clientWidth)return;const delta=Math.abs(e.deltaY)>Math.abs(e.deltaX)?e.deltaY:e.deltaX;if(!delta)return;e.preventDefault();el.scrollLeft+=delta;},{passive:false});
$('courseViewToggle').addEventListener('click',()=>{const resources=$('resources');resources.classList.remove('view-changing');void resources.offsetWidth;resources.classList.add('view-changing');setTimeout(()=>resources.classList.remove('view-changing'),260);});
let metadataTab='tag',metadataRows=null,loadedMetadataTab='';
async function renderMetadata(reload=false){if(reload||!metadataRows||loadedMetadataTab!==metadataTab){metadataRows=await api(metadataTab==='tag'?'tags':'authors');loadedMetadataTab=metadataTab;}$('metadataView').querySelectorAll('[data-meta-tab]').forEach(button=>button.setAttribute('aria-current',String(button.dataset.metaTab===metadataTab)));const needle=foldText($('metadataSearch').value);const rows=(metadataRows||[]).filter(row=>foldText(metadataTab==='tag'?row.tag:row.author).includes(needle)).map(row=>{const name=metadataTab==='tag'?row.tag:row.author;return `<div class="metadata-row" title="${esc(name)}"><button class="metadata-name" data-meta-open="${esc(name)}">${icon(metadataTab==='tag'?'tag':'user')}<span class="meta-title">${esc(metadataTab==='tag'?'+':'')}${esc(name)}</span></button><span class="metadata-count">${row.total}</span><div class="metadata-actions"><button class="icon-button" data-meta-rename="${esc(name)}" title="Renombrar" aria-label="Renombrar ${esc(name)}">${icon('document')}</button><button class="icon-button" data-meta-delete="${esc(name)}" title="Eliminar" aria-label="Eliminar ${esc(name)}">${icon('trash')}</button></div></div>`;}).join('');$('metadataItems').innerHTML=rows?rows:'<p class="metadata-empty">No hay resultados.</p>';}
$('metadata').onclick=guard(async()=>{await flush();if(S.view==='course'){const el=pop($('metadata'));if(!el)return;const tags=new Set(),authors=new Set();for(const row of S.resources){for(const tag of String(row.etiquetas||'').split(/\s+/).filter(Boolean))tags.add(tag);for(const author of String(row.autor||'').split('\n').filter(Boolean))authors.add(author);}el.innerHTML='<div class="field-label">ETIQUETAS</div>'+([...tags].sort().map(tag=>`<button data-course-token="${esc(tag)}">${esc(tag)}</button>`).join('')||'<small>Sin etiquetas</small>')+'<div class="field-label">AUTORES</div>'+([...authors].sort().map(author=>`<button data-course-token="${esc('@autor:'+author)}">${esc(author)}</button>`).join('')||'<small>Sin autores</small>');el.onclick=guard(async e=>{const token=e.target.closest('[data-course-token]')?.dataset.courseToken;if(token){el.hidden=true;await addToken(token);}});return;}if(S.view==='metadata'){setView('grid');return;}setView('metadata');await renderMetadata(true);});
async function finishTaxonomyEdit(operation,oldName,newName=''){await api('taxonomy_edit',{kind:metadataTab,operation,old:oldName,new:newName});tagCatalog=null;authorCatalog=null;metadataRows=null;await renderMetadata(true);await refresh();}
$('metadataView').onclick=guard(async e=>{const tab=e.target.closest('[data-meta-tab]');if(tab){metadataTab=tab.dataset.metaTab;await renderMetadata(true);return;}const rename=e.target.closest('[data-meta-rename]'),remove=e.target.closest('[data-meta-delete]'),open=e.target.closest('[data-meta-open]');if(!rename&&!remove&&!open)return;const name=rename?.dataset.metaRename||remove?.dataset.metaDelete||open?.dataset.metaOpen;if(open){await addToken(metadataTab==='tag'?'+'+name:'@autor:'+name);return;}if(rename){const row=rename.closest('.metadata-row'),field=document.createElement('input');field.className='metadata-inline';field.value=name;row.querySelector('.metadata-name').replaceWith(field);field.focus();field.select();let committed=false;field.onkeydown=guard(async event=>{if(event.key==='Escape'){committed=true;await renderMetadata();return;}if(event.key==='Enter'){event.preventDefault();const value=field.value.trim();if(value){committed=true;await finishTaxonomyEdit('rename',name,value);}}});field.onblur=guard(async()=>{if(committed)return;committed=true;const value=field.value.trim();if(value&&value!==name)await finishTaxonomyEdit('rename',name,value);else await renderMetadata();});return;}$('dialogTitle').textContent=`Eliminar ${metadataTab==='tag'?'etiqueta':'autor'}`;$('dialogBody').innerHTML=`<p>Se quitará “${esc(name)}” de todos los elementos de este perfil.</p><button class="text-button danger-button" id="confirmMetaDelete">Eliminar</button>`;$('dialogBody').querySelector('#confirmMetaDelete').onclick=guard(async()=>{await finishTaxonomyEdit('delete',name);$('dialog').close();});$('dialog').showModal();});
$('metadataSearch').oninput=()=>renderMetadata(false);
function applyMode(){$('mode').innerHTML=icon(S.mode==='web'?'web':'local');$('mode').title='Modo de apertura: '+S.mode;const ml=$('modeLabel');if(ml)ml.textContent=S.mode==='web'?'Web':'Local';}
$('mode').onclick=guard(async()=>{S.mode=S.mode==='local'?'web':'local';applyMode();await api('preference',{key:'modo',value:S.mode});});
async function deleteSelected(confirmed=false){const ids=S.bulkIds.size?[...S.bulkIds]:S.selected?[S.selected.drive_id]:[];if(!ids.length)return;if(S.confirmDelete&&!confirmed){const dialog=$('dialog');$('dialogTitle').textContent=ids.length===1?'Eliminar elemento':'Eliminar elementos';$('dialogBody').replaceChildren();const message=document.createElement('p');message.textContent=ids.length===1?'El elemento se moverá a la papelera de Drive. ¿Continuar?':`${ids.length} elementos se moverán a la papelera de Drive. ¿Continuar?`;const confirm=document.createElement('button');confirm.className='text-button danger-button';confirm.textContent='Mover a la papelera';confirm.onclick=guard(async()=>{dialog.close();await deleteSelected(true);});const cancel=document.createElement('button');cancel.className='text-button';cancel.textContent='Cancelar';cancel.onclick=()=>dialog.close();$('dialogBody').append(message,confirm,cancel);dialog.showModal();return;}for(const id of ids)await api('delete_item',{id});S.bulkIds.clear();S.selected=null;$('details').hidden=true;$('inspectorEmpty').hidden=false;await refresh();notify(ids.length===1?'Movido a la papelera de Drive':`${ids.length} elementos movidos a la papelera de Drive`);}
let undoingDeletion=false;
document.addEventListener('keydown',guard(async e=>{
 if(!(e.ctrlKey||e.metaKey)||e.shiftKey||e.altKey||e.key.toLowerCase()!=='z'||undoingDeletion||$('dialog').open||(e.target instanceof Element&&e.target.closest('input,textarea,select,[contenteditable]')))return;
 e.preventDefault();undoingDeletion=true;
 try{
  const result=await api('undo_delete');
  if(!result.restored){notify('No hay eliminaciones para deshacer');return;}
  if(S.view==='course'&&S.course){S.resources=await api('container',{id:S.course.drive_id});clearCourseSelection();renderResources();}
  await refresh();
  notify(`Restaurado: ${result.name}`);
 }finally{undoingDeletion=false;}
}));
document.addEventListener('keydown',guard(async e=>{if(e.key!=='Delete'||S.view!=='grid'||e.target.closest('input,textarea,select,[contenteditable]')||$('dialog').open)return;e.preventDefault();await deleteSelected();}));
function applyTheme(){document.documentElement.dataset.theme=S.theme==='auto'?(matchMedia('(prefers-color-scheme:light)').matches?'light':'dark'):S.theme;}
matchMedia('(prefers-color-scheme:light)').addEventListener('change',applyTheme);
document.addEventListener('pointercancel',()=>{swiping=false;swipeTokens.clear();renderFilters();});
let diceMode=0;
function updateDiceUI(){
 $('dice').classList.toggle('target',diceMode===2);
 $('dice').innerHTML=icon(['similar','dice','target'][diceMode]);
 $('dice').removeAttribute('title');
 $('dice').setAttribute('aria-label',['Buscar relacionados','Descubrir aleatoriamente','Descubrir según tus intereses'][diceMode]+' · rueda o clic derecho para cambiar');
 animateControl($('dice'),'mode-change');
}
updateDiceUI();
$('dice').addEventListener('wheel',e=>{e.preventDefault();diceMode=(diceMode+(e.deltaY>0?1:2))%3;updateDiceUI();},{passive:false});
$('dice').addEventListener('contextmenu',e=>{e.preventDefault();diceMode=(diceMode+1)%3;updateDiceUI();});
$('similar').onclick=guard(async()=>{if(S.view==='course'){const selected=S.resources.find(row=>row.id===S.courseSelection?.id);if(!selected){notify('Selecciona un recurso.');return;}const token='@tipo:'+(selected.tipo_contenido||'otro');S.tokens=S.tokens.includes(token)?S.tokens.filter(value=>value!==token):[...S.tokens.filter(value=>!value.startsWith('@tipo:')),token];await refresh(true);return;}if(S.similarIds){S.similarIds=null;$('similar').setAttribute('aria-pressed','false');await refresh(true);notify('Vista completa restaurada');return;}if(!S.selected){notify('Selecciona primero un elemento.');return;}await flush();const result=await api('similar',{id:S.selected.drive_id});if(!result.ids.length){notify('No encontré elementos similares.');return;}S.tokens=[];ghostHide();S.similarIds=result.ids;$('similar').setAttribute('aria-pressed','true');setView('grid');await refresh(true);notify(result.ids.length>1?`${result.ids.length-1} similares por ${result.basis}`:'No hay otros elementos similares.');});
$('dice').onclick=guard(async()=>{
 if(S.view==='course'){const rows=[...$('resources').querySelectorAll('[data-resource-key]')];if(rows.length){const row=rows[Math.floor(Math.random()*rows.length)];await courseSelectFromEvent(row,{shiftKey:false,ctrlKey:false,metaKey:false});row.scrollIntoView({block:'nearest'});}return;}
 if(diceMode===0){$('similar').click();return;}
 $('dice').classList.remove('spinning');
 void $('dice').offsetWidth;
 $('dice').classList.add('spinning');
 setTimeout(()=>$('dice').classList.remove('spinning'),700);
 await flush();
 const item=await api('random',{contextual:diceMode===2});
 if(!item)return;
 S.tokens=[];setView('grid');await refresh();await select(item.drive_id,true);
 const i=S.items.findIndex(r=>r.drive_id===item.drive_id),levels=zoomLevels(),v=$('viewport'),w=levels.width,c=Math.max(levels.min,Math.min(levels.max,Math.floor((w+20)/(S.zoom+20)))),cw=(w-20*(c-1))/c;
 v.scrollTop=Math.floor(i/c)*(Math.round(cw*1.25)+captionHeightForColumns(c,levels)+22);
 scheduleDraw();
});
let zoomTimer=null,zoomingTimer=null;
function zoomLevels(){const width=$('viewport').clientWidth-56,gap=20,baseMin=Math.max(2,Math.floor((width+gap)/(430+gap))+1),min=baseMin+1,max=min+3;return {width,gap,min,max};}
function captionHeightForColumns(columns){return Number(columns)>=4?110:92;}
function changeZoom(direction,wrap=false){const levels=zoomLevels(),{width,gap,min,max}=levels,total=width+gap,current=Math.max(min,Math.min(max,Math.floor(total/(S.zoom+gap))));let columns=current-direction;if(columns<min)columns=wrap?max:min;if(columns>max)columns=wrap?min:max;if(columns===current)return;const v=$('viewport'),oldWidth=(width-gap*(current-1))/current,oldStride=Math.round(oldWidth*1.25)+captionHeightForColumns(current)+22,firstRow=Math.floor(v.scrollTop/oldStride);zoomAnchor={index:firstRow*current,fraction:(v.scrollTop-firstRow*oldStride)/oldStride};const upper=total/columns-gap,lower=total/(columns+1)-gap;S.zoom=Math.max(60,Math.min(430,Math.round((upper+lower)/2)));updateGridIcon(columns,true);const canvas=$('canvas');canvas.classList.add('is-zooming');clearTimeout(zoomingTimer);zoomingTimer=setTimeout(()=>canvas.classList.remove('is-zooming'),280);drawNow();clearTimeout(zoomTimer);zoomTimer=setTimeout(()=>api('preference',{key:'zoom',value:S.zoom}).catch(error=>{if(error.message!=='Zoom inválido')report(error);}),350);}
function cycleZoom(){changeZoom(1,true);}
$('zoom').onclick=guard(cycleZoom);
$('zoom').addEventListener('wheel',e=>{e.preventDefault();changeZoom(e.deltaY<0?1:-1);},{passive:false});
document.addEventListener('wheel',e=>{
 if(!e.ctrlKey||e.target.closest('#zoom'))return;
 e.preventDefault();
 changeZoom(e.deltaY<0?1:-1);
},{passive:false});
async function applyWallpaper(filename){S.wallpaper=filename||'';const backdrop=$('wallpaperBackdrop');backdrop.style.backgroundPosition=S.wallpaperPositions[S.wallpaper]===false?'left top':'center';if(!S.wallpaper){document.body.classList.remove('has-wallpaper');backdrop.style.backgroundImage='none';return;}try{const src=await api('get_wallpaper',{filename:S.wallpaper});if(src){backdrop.style.backgroundImage=`url("${src}")`;document.body.classList.add('has-wallpaper');}else{document.body.classList.remove('has-wallpaper');backdrop.style.backgroundImage='none';}}catch(e){document.body.classList.remove('has-wallpaper');backdrop.style.backgroundImage='none';}}
let containerWallpaperSource='',containerWallpaperRevision=0,containerBlurTimer=null;
async function renderContainerWallpaper(){const source=containerWallpaperSource,revision=++containerWallpaperRevision,root=document.documentElement;if(!source){root.style.setProperty('--container-wallpaper-image','none');return;}if(!S.containerBackgroundBlur){root.style.setProperty('--container-wallpaper-image',`url("${source}")`);return;}const image=new Image();image.src=source;try{await image.decode();}catch{return;}if(revision!==containerWallpaperRevision)return;const scale=Math.min(1,1600/image.width,1200/image.height),width=Math.max(1,Math.round(image.width*scale)),height=Math.max(1,Math.round(image.height*scale)),canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;const context=canvas.getContext('2d');if(!context)return;const blur=S.containerBackgroundBlur*scale,extra=Math.max(blur*3,8);context.filter=`blur(${blur}px)`;context.drawImage(image,-extra,-extra,width+extra*2,height+extra*2);if(revision===containerWallpaperRevision)root.style.setProperty('--container-wallpaper-image',`url("${canvas.toDataURL('image/jpeg',.88)}")`);}
async function applyContainerWallpaper(filename){S.containerWallpaper=filename||'';const root=document.documentElement;if(!S.containerWallpaper){containerWallpaperSource='';await renderContainerWallpaper();return;}try{containerWallpaperSource=await api('get_wallpaper',{filename:S.containerWallpaper})||'';root.style.setProperty('--container-wallpaper-position',S.wallpaperPositions[S.containerWallpaper]===false?'left top':'center');await renderContainerWallpaper();}catch{containerWallpaperSource='';await renderContainerWallpaper();}}
function applyWallpaperOpacity(value){S.wallpaperOpacity=Math.max(0,Math.min(100,Number(value)||0));document.documentElement.style.setProperty('--wallpaper-dim',String((100-S.wallpaperOpacity)/100));}
function applyWallpaperBlur(value){S.wallpaperBlur=Math.max(0,Math.min(30,Number(value)||0));document.documentElement.style.setProperty('--wallpaper-blur',S.wallpaperBlur+'px');}
function applyContainerBackgroundOpacity(value){S.containerBackgroundOpacity=Math.max(0,Math.min(100,Number(value)||0));document.documentElement.style.setProperty('--container-background-opacity',S.containerBackgroundOpacity+'%');}
function applyContainerBackgroundBlur(value){S.containerBackgroundBlur=Math.max(0,Math.min(30,Number(value)||0));document.documentElement.style.setProperty('--container-background-blur',S.containerBackgroundBlur+'px');clearTimeout(containerBlurTimer);if(containerWallpaperSource)containerBlurTimer=setTimeout(()=>renderContainerWallpaper().catch(report),80);}
const wallpaperContextMenu=document.createElement('div');wallpaperContextMenu.id='wallpaperContextMenu';wallpaperContextMenu.className='wallpaper-context-menu';wallpaperContextMenu.setAttribute('role','menu');wallpaperContextMenu.hidden=true;document.body.append(wallpaperContextMenu);
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!wallpaperContextMenu.hidden){e.preventDefault();e.stopImmediatePropagation();wallpaperContextMenu.hidden=true;}},true);
function openWallpaperContextMenu(item,event){const filename=item.dataset.wp,centered=S.wallpaperPositions[filename]!==false,removable=item.dataset.removable==='true';wallpaperContextMenu.dataset.filename=filename;wallpaperContextMenu.innerHTML=`<button type="button" role="menuitemcheckbox" aria-checked="${centered}" data-wallpaper-center>${centered?'✓ ':''}Centrar imagen</button><button type="button" role="menuitem" data-wallpaper-delete ${removable?'':'disabled title="Solo se pueden eliminar fondos añadidos"'}>Eliminar fondo</button>`;wallpaperContextMenu.hidden=false;const width=wallpaperContextMenu.offsetWidth,height=wallpaperContextMenu.offsetHeight;wallpaperContextMenu.style.left=Math.max(8,Math.min(event.clientX,innerWidth-width-8))+'px';wallpaperContextMenu.style.top=Math.max(8,Math.min(event.clientY,innerHeight-height-8))+'px';wallpaperContextMenu.querySelector('[data-wallpaper-center]').focus();}
wallpaperContextMenu.onclick=guard(async event=>{const filename=wallpaperContextMenu.dataset.filename;if(event.target.closest('[data-wallpaper-center]')){const centered=!(S.wallpaperPositions[filename]!==false);await api('set_wallpaper_centered',{filename,centered});S.wallpaperPositions[filename]=centered;if(S.wallpaper===filename)await applyWallpaper(filename);if(S.containerWallpaper===filename)await applyContainerWallpaper(filename);wallpaperContextMenu.hidden=true;notify(centered?'Imagen centrada':'Imagen alineada arriba a la izquierda');return;}if(event.target.closest('[data-wallpaper-delete]:not(:disabled)')){const result=await api('delete_wallpaper',{filename});delete S.wallpaperPositions[filename];wallpaperContextMenu.hidden=true;if(result.active)await applyWallpaper('');if(result.activeContainer)await applyContainerWallpaper('');const el=$('popover');if(!el.hidden&&el.classList.contains('wallpaper-popover'))await renderWallpaperPopover(el);notify('Fondo eliminado');}});
function setupDualControl(menu,controls){
 const track=menu.querySelector('.wallpaper-dual');
 const thumbs={opacity:track.querySelector('[data-setting=opacity]'),blur:track.querySelector('[data-setting=blur]')};
 const value=controls.value;
 const max=setting=>setting==='opacity'?100:30;
 function render(){const half=(track.clientWidth-34)/2;for(const setting of ['blur','opacity']){const thumb=thumbs[setting],position=setting==='blur'?8+half*value(setting)/max(setting):26+half+half*value(setting)/max(setting);thumb.style.left=`${position}px`;thumb.setAttribute('aria-valuenow',String(value(setting)));}track.style.setProperty('--range-left',thumbs.blur.style.left);track.style.setProperty('--range-right',thumbs.opacity.style.left);}
 function update(setting,next){controls.apply(setting,Math.round(next));render();}
 function save(setting){return controls.save(setting,value(setting));}
 function pointerValue(event,setting){const rect=track.getBoundingClientRect(),half=(rect.width-34)/2,x=event.clientX-rect.left;return setting==='blur'?Math.max(0,Math.min(1,(x-8)/half))*30:Math.max(0,Math.min(1,(x-26-half)/half))*100;}
 let dragging=null;
 track.onpointerdown=event=>{if(event.button!==0)return;const direct=event.target.closest('.wallpaper-thumb')?.dataset.setting;if(direct)dragging=direct;else{const x=event.clientX-track.getBoundingClientRect().left;dragging=Math.abs(x-parseFloat(thumbs.opacity.style.left))<=Math.abs(x-parseFloat(thumbs.blur.style.left))?'opacity':'blur';}track.setPointerCapture(event.pointerId);update(dragging,pointerValue(event,dragging));event.preventDefault();};
 track.onpointermove=event=>{if(dragging)update(dragging,pointerValue(event,dragging));};
 const finish=guard(async()=>{if(!dragging)return;const setting=dragging;dragging=null;await save(setting);});
 track.onpointerup=finish;track.onpointercancel=finish;
 for(const setting of ['opacity','blur'])thumbs[setting].onkeydown=guard(async event=>{const step=event.key==='ArrowRight'||event.key==='ArrowUp'?1:event.key==='ArrowLeft'||event.key==='ArrowDown'?-1:0;if(!step)return;event.preventDefault();update(setting,value(setting)+step);await save(setting);});
 render();
}
function setupWallpaperDualControl(menu){setupDualControl(menu,{value:setting=>setting==='opacity'?S.wallpaperOpacity:S.wallpaperBlur,apply:(setting,value)=>setting==='opacity'?applyWallpaperOpacity(value):applyWallpaperBlur(value),save:(setting,value)=>api('preference',{key:setting==='opacity'?'wallpaper_opacity':'wallpaper_blur',value})});}
function setupContainerBackgroundDualControl(menu){setupDualControl(menu,{value:setting=>setting==='opacity'?S.containerBackgroundOpacity:S.containerBackgroundBlur,apply:(setting,value)=>setting==='opacity'?applyContainerBackgroundOpacity(value):applyContainerBackgroundBlur(value),save:(setting,value)=>api('preference',{key:setting==='opacity'?'container_background_opacity':'container_background_blur',value})});}
function wallpaperAssignmentBadges(filename){return `<span class="wallpaper-assignment-badges">${S.wallpaper===filename?'<span>1</span>':''}${S.containerWallpaper===filename?'<span>2</span>':''}</span>`;}
function updateWallpaperAssignments(menu){const current=S.wallpaperTarget===1?S.wallpaper:S.containerWallpaper;menu.querySelectorAll('.wallpaper-item').forEach(button=>button.classList.toggle('active',(button.dataset.wp||'')===current));menu.querySelectorAll('.wallpaper-item[data-wp]:not(.none)').forEach(button=>{button.querySelector('.wallpaper-assignment-badges')?.remove();button.insertAdjacentHTML('beforeend',wallpaperAssignmentBadges(button.dataset.wp));});menu.querySelectorAll('[data-wallpaper-target]').forEach(button=>button.setAttribute('aria-pressed',String(Number(button.dataset.wallpaperTarget)===S.wallpaperTarget)));}
async function renderWallpaperPopover(el){
 const list=await api('wallpapers_list');
 el.innerHTML=`<div class="wallpaper-head"><button type="button" class="wallpaper-target" data-wallpaper-target="1" aria-label="Elegir Biblioteca" aria-pressed="true">1</button><span>Biblioteca</span><div class="wallpaper-dual"><button type="button" class="wallpaper-thumb" data-setting="blur" role="slider" aria-label="Desenfoque de Biblioteca" aria-valuemin="0" aria-valuemax="30"></button><button type="button" class="wallpaper-thumb" data-setting="opacity" role="slider" aria-label="Opacidad de Biblioteca" aria-valuemin="0" aria-valuemax="100"></button></div></div><div class="container-background-controls"><div class="wallpaper-head"><button type="button" class="wallpaper-target" data-wallpaper-target="2" aria-label="Elegir Explorador" aria-pressed="false">2</button><span>Explorador</span><div class="wallpaper-dual"><button type="button" class="wallpaper-thumb" data-setting="blur" role="slider" aria-label="Desenfoque de Explorador" aria-valuemin="0" aria-valuemax="30"></button><button type="button" class="wallpaper-thumb" data-setting="opacity" role="slider" aria-label="Opacidad de Explorador" aria-valuemin="0" aria-valuemax="100"></button></div></div></div><div class="wallpaper-list"><button class="wallpaper-item none ${!(S.wallpaperTarget===1?S.wallpaper:S.containerWallpaper)?'active':''}" data-wp="" title="Sin fondo para el destino seleccionado"><span>⊘ Sin fondo</span></button>${list.map(w=>`<button class="wallpaper-item ${(S.wallpaperTarget===1?S.wallpaper:S.containerWallpaper)===w.filename?'active':''}" data-wp="${esc(w.filename)}" data-removable="${w.removable}" title="${esc(w.name)} · clic derecho para asignarlo al destino seleccionado"><span>${esc(w.name)}</span>${wallpaperAssignmentBadges(w.filename)}</button>`).join('')}</div><button type="button" class="wallpaper-upload" id="uploadWp">+ Añadir imagen…</button><div class="theme-row">${[['light','Modo claro','themeLight'],['dark','Modo oscuro','themeDark'],['auto','Automático','theme']].map(([key,label,symbol])=>`<button type="button" data-theme="${key}" aria-label="${label}" title="${label}" aria-current="${S.theme===key}">${icon(symbol)}</button>`).join('')}</div>`;
 setupWallpaperDualControl(el);
 setupContainerBackgroundDualControl(el.querySelector('.container-background-controls'));
 updateWallpaperAssignments(el);
 for(const item of list){
  api('get_wallpaper',{filename:item.filename,thumb:true}).then(src=>{
   const btn=[...el.querySelectorAll('[data-wp]')].find(b=>b.dataset.wp===item.filename);
   if(btn&&src&&!btn.querySelector('img')){
    const img=document.createElement('img');
    img.src=src;
    img.alt=item.name;
    btn.prepend(img);
   }
  }).catch(()=>{});
 }
}
$('wallpaper').onclick=guard(async()=>{
 const el=pop($('wallpaper'));
 if(!el)return;
 el.classList.add('wallpaper-popover');
 el.innerHTML='<div class="wallpaper-head"><span>FONDOS</span></div><p style="font-size:10px;color:var(--muted);padding:8px">Cargando fondos…</p>';
 await renderWallpaperPopover(el);
 el.oncontextmenu=e=>{const item=e.target.closest('.wallpaper-item[data-wp]:not(.none)');if(!item)return;e.preventDefault();openWallpaperContextMenu(item,e);};
 el.onclick=guard(async e=>{
  const targetButton=e.target.closest('[data-wallpaper-target]');
  if(targetButton){S.wallpaperTarget=Number(targetButton.dataset.wallpaperTarget);updateWallpaperAssignments(el);return;}
  const themeBtn=e.target.closest('.theme-row button[data-theme]');
  if(themeBtn){
   S.theme=themeBtn.dataset.theme;
   applyTheme();
   await api('preference',{key:'tema',value:S.theme});
   el.querySelectorAll('[data-theme]').forEach(button=>button.setAttribute('aria-current',String(button.dataset.theme===S.theme)));
   return;
  }
  const uploadBtn=e.target.closest('#uploadWp');
  if(uploadBtn){
   $('wallpaperFile').value='';
   $('wallpaperFile').click();
   return;
  }
  const wpBtn=e.target.closest('[data-wp]');
  if(wpBtn){
   const selected=wpBtn.dataset.wp||'';
   const key=S.wallpaperTarget===1?'wallpaper':'container_wallpaper';
   await api('preference',{key,value:selected});
   if(S.wallpaperTarget===1)await applyWallpaper(selected);else await applyContainerWallpaper(selected);
   updateWallpaperAssignments(el);
   notify(selected?`Fondo ${S.wallpaperTarget===1?'de Biblioteca':'del Explorador'} aplicado`:'Fondo predeterminado');
  }
 });
});
$('wallpaperFile').onchange=guard(async e=>{
 const file=e.target.files?.[0];
 e.target.value='';
 if(!file)return;
 if(!['image/jpeg','image/png','image/webp'].includes(file.type))throw Error('Usa formatos JPG, PNG o WEBP');
 if(file.size>20_000_000)throw Error('La imagen no debe superar los 20 MB');
 $('status').textContent=`Guardando fondo de ${S.wallpaperTarget===1?'Biblioteca':'Explorador'}…`;
 const data=await new Promise((resolve,reject)=>{
  const r=new FileReader();
  r.onload=()=>resolve(r.result.split(',')[1]);
  r.onerror=reject;
  r.readAsDataURL(file);
 });
 const res=await api('save_wallpaper',{name:file.name,data});
 await api('preference',{key:S.wallpaperTarget===1?'wallpaper':'container_wallpaper',value:res.filename});
 if(S.wallpaperTarget===1)await applyWallpaper(res.filename);else await applyContainerWallpaper(res.filename);
 const popover=$('popover');
 if(!popover.hidden&&popover.classList.contains('wallpaper-popover')){
  await renderWallpaperPopover(popover);
 }
 notify(S.wallpaperTarget===1?'Fondo de Biblioteca guardado y aplicado':'Fondo del Explorador guardado y aplicado');
 $('status').textContent='Fondo aplicado';
});
$('sync').onclick=guard(async()=>{await flush();$('sync').disabled=true;$('status').textContent='Sincronizando…';try{const drive=await api('drive_status');if(!(await showDriveSetup(drive)))return;const result=await api('sync');tagCatalog=null;authorCatalog=null;await refresh();$('status').textContent=result.indexados+' piezas sincronizadas';if(result.revinculados)notify(`${result.revinculados} ${result.revinculados===1?'elemento recuperado':'elementos recuperados'} con sus datos`,'success');}finally{$('sync').disabled=false;}});
async function renderCovers(ids,mode){await flush();if(!ids.length)throw Error('Selecciona uno o más elementos.');$('status').textContent=mode==='local'?'Generando portadas…':'Preparando Colab…';const result=await api(mode==='local'?'render_covers_local':'render_covers_colab',{ids});if(mode==='local'){for(const id of result.ids){S.covers.delete(id);coverCache.delete(id);}await refresh();notify(`${result.rendered} portadas generadas${result.failed.length?` · ${result.failed.length} sin generar`:''}`);}else notify(`${result.queued} portadas enviadas a Colab. Ejecuta la celda del cuaderno.`);$('status').textContent='Biblioteca local · Lista';}
if($('covers'))$('covers').onclick=guard(async()=>{const el=pop($('covers'));if(!el)return;el.innerHTML='<button data-cover-mode="local">💻 Renderizar en este equipo</button><button data-cover-mode="colab">⚡ Renderizar en Google Colab</button>';el.onclick=guard(async e=>{const mode=e.target.closest('[data-cover-mode]')?.dataset.coverMode;if(!mode)return;el.hidden=true;popoverAnchor=null;await renderCovers(S.bulkIds.size?[...S.bulkIds]:S.selected?[S.selected.drive_id]:[],mode);});});
setInterval(async()=>{if(!ready||!$('setupView').hidden)return;try{const result=await api('cover_batch_check');if(result.imported){S.covers.clear();coverCache.clear();await refresh();notify(`${result.imported} portadas recibidas de Colab`,'success');}}catch(error){console.warn('No se pudo importar el lote de portadas',error);}},15000);
$('driveTools').onclick=guard(async()=>{await flush();const el=pop($('driveTools'));if(!el)return;el.classList.add('drive-tools-popover');el.innerHTML='<div id="driveToolsBody" class="drive-tools-list">Cargando…</div>';const profiles=await api('profiles');el.querySelector('#driveToolsBody').innerHTML=profiles.map(profile=>`<button type="button" class="profile-choice${profile.id===S.profileId?' active':''}" data-profile="${esc(profile.id)}" aria-current="${profile.id===S.profileId}" ${profile.error?'disabled':''} title="${esc(profile.id)}${profile.id===S.profileId?' · Cuenta actual':''}">${icon('user')}<span>${esc(profile.id)}</span></button>`).join('')+'<div class="drive-tools-divider"></div><button type="button" class="backup-choice" data-backup>'+icon('backup')+'<span>Crear copia de seguridad en Drive</span></button>';el.onclick=guard(async e=>{const account=e.target.closest('[data-profile]');if(account){if(account.disabled)return;el.hidden=true;popoverAnchor=null;if(account.dataset.profile!==S.profileId)await selectDriveProfile(account.dataset.profile);return;}const backup=e.target.closest('[data-backup]');if(backup){if(backup.disabled)return;backup.disabled=true;const prevContent=backup.innerHTML;backup.innerHTML=icon('refresh')+'<span>Creando copia de seguridad…</span>';$('status').textContent='Creando copia de seguridad en Drive…';try{await api('backup');notify('Copia de seguridad guardada en Drive');el.hidden=true;popoverAnchor=null;$('status').textContent='Copia de seguridad lista';}catch(err){report(err);backup.disabled=false;backup.innerHTML=prevContent;}}});});
$('viewport').addEventListener('keydown',guard(async e=>{
 if(S.view!=='grid'||e.altKey||e.ctrlKey||e.metaKey)return;
 const card=e.target.closest('.card');if(!card&&e.target!==$('viewport'))return;
 const selectedIndex=S.items.findIndex(item=>item.drive_id===S.selected?.drive_id),current=card?Number(card.dataset.index):Math.max(0,selectedIndex),width=$('viewport').clientWidth-56,cols=Math.max(1,Math.floor((width+20)/(S.zoom+20)));
 if(e.key==='Tab'&&!e.shiftKey&&card){e.preventDefault();await select(S.items[current].drive_id);($('inspector').classList.contains('is-compact')?inspectorToggle:$('hero')).focus();return;}
 const next=({ArrowLeft:current-1,ArrowRight:current+1,ArrowUp:current-cols,ArrowDown:current+cols,Home:0,End:S.items.length-1})[e.key];
 if(next===undefined)return;e.preventDefault();if(next>=0&&next<S.items.length)await focusCardIndex(next);
}));
$('inspector').addEventListener('keydown',guard(async e=>{if(e.key==='Tab'&&e.shiftKey&&e.target===$('hero')){const index=S.items.findIndex(item=>item.drive_id===keyboardCardId);if(index>=0){e.preventDefault();await focusCardIndex(index,false);}}}));
$('viewport').addEventListener('scroll',scheduleDraw,{passive:true});new ResizeObserver(scheduleDraw).observe($('viewport'));
function renderImportPanel(){const panel=$('importPanel');if(panel.hidden)return;const jobs=[...importJobs.values()].filter(job=>job.kind===importTab).reverse();panel.innerHTML=`<div class="import-tabs" role="tablist" aria-label="Tipos de cargas"><button type="button" role="tab" data-import-tab="folder" aria-selected="${importTab==='folder'}">Contenedores</button><button type="button" role="tab" data-import-tab="file" aria-selected="${importTab==='file'}">Elementos</button></div>`+(jobs.length?jobs.map(job=>`<div class="import-row"><strong>${esc(job.name)}</strong><div class="import-row-action">${job.state==='running'?`<button class="import-action" type="button" data-cancel="${job.id}" title="Cancelar carga" aria-label="Cancelar carga de ${esc(job.name)}">${icon('close')}</button>`:job.state==='done'?`<button class="import-action" type="button" data-delete="${job.id}" title="Eliminar de Drive" aria-label="Eliminar ${esc(job.name)} de Drive">${icon('trash')}</button>`:''}</div>${job.state==='running'?`<span>${esc(job.message||'Subiendo…')}</span>`:job.state==='done'?`<span class="import-done" title="Copiado en Drive; la sincronización con Google continúa en segundo plano">${icon('status')}<span>Copiado en Drive</span></span>`:`<span>${esc(job.message||job.state)}</span>`}</div>`).join(''):'<p>No hay cargas recientes en esta sección.</p>');}
function startImportUi(name,kind,id){if(importJobs.has(id))return;importJobs.set(id,{id,name,kind,state:'running',message:'Subiendo a Drive'});importTab=kind;setImportNotice('running');renderImportPanel();notify(`Comenzó la carga a Drive: ${name}`,'working');pollImport(id);}
async function requestImportCancel(id){const job=importJobs.get(id);if(!job||job.state!=='running')return;job.message='Cancelando y eliminando la copia…';renderImportPanel();try{await api('cancel_import',{id});}catch(error){notify(error.message,'error');}}
async function pollImport(id){while(importJobs.get(id)?.state==='running'){try{const state=await api('import_status',{id});importJobs.set(id,{...importJobs.get(id),...state});renderImportPanel();if(['done','cancelled','error','unknown'].includes(state.state)){await window.balisco.importFinished({ok:state.state==='done',cancelled:state.state==='cancelled',id,data:state.data,error:state.error||state.message});return;}}catch(error){await window.balisco.importFinished({ok:false,id,error:error.message});return;}await new Promise(resolve=>setTimeout(resolve,700));}}
$('imports').onclick=()=>{const panel=$('importPanel');panel.hidden=!panel.hidden;setImportNotice('');if(!panel.hidden){$('popover').hidden=true;popoverAnchor=null;panel.style.right=Math.max(12,innerWidth-$('imports').getBoundingClientRect().right)+'px';renderImportPanel();}};
$('importPanel').onclick=async event=>{const tab=event.target.closest('[data-import-tab]');if(tab){importTab=tab.dataset.importTab;renderImportPanel();return;}const cancel=event.target.closest('[data-cancel]');if(cancel){requestImportCancel(cancel.dataset.cancel);return;}const remove=event.target.closest('[data-delete]');if(remove){const job=importJobs.get(remove.dataset.delete);remove.disabled=true;try{await api('delete_import',{id:job.id});job.state='deleted';job.message='Eliminado de Drive';renderImportPanel();notify(`Eliminado de Drive: ${job.name}`,'success');}catch(error){remove.disabled=false;notify(error.message,'error');}}};
window.balisco={flush,windowState,close:guard(async()=>{await flush();await api('close');}),state:S,nativeDrop:true,importStarted:startImportUi,importRejected:message=>{setImportNotice('error');notify(`Error al subir: ${message}`,'error');},importFinished:async result=>{const job=importJobs.get(result.id);if(!job||job.finished)return;job.finished=true;job.state=result.cancelled?'cancelled':result.ok?'done':'error';job.message=result.cancelled?`Cancelado: ${job.name}`:result.ok?`Copiado a Drive: ${job.name}`:result.error||`Error al subir: ${job.name}`;const jobs=[...importJobs.values()];setImportNotice(jobs.some(item=>item.state==='error')?'error':jobs.some(item.state==='running')?'running':'done');renderImportPanel();if(!result?.ok){notify(result?.cancelled?`Cancelado: ${job.name}`:`Error al subir ${job.name}: ${job.message}`,'error');return;}notify(`Copiado a Drive: ${job.name}`,'success');try{await api('sync');await refresh();}catch(error){notify(`Copia terminada. Sincroniza cuando Drive termine de registrar el archivo: ${error.message}`,'error');}}};
async function loadActiveProfile(){
 S.loading=true;scheduleDraw();
 try{
  const result=await api('bootstrap');
 S.profileId=result.prefs.id_perfil_drive||'';
 S.mode=result.prefs.modo||'local';
 S.confirmDelete=result.prefs.confirm_delete!=='false';
 S.showRecentTitles=result.prefs.show_recent_titles==='true';
 S.languages=result.languages||['Español','Inglés'];
 S.theme=result.prefs.tema||'auto';
 S.zoom=Number(result.prefs.zoom)||195;
 try{S.wallpaperPositions=JSON.parse(result.prefs.wallpaper_positions||'{}');}catch{S.wallpaperPositions={};}
 applyWallpaperOpacity(result.prefs.wallpaper_opacity??24);
 applyWallpaperBlur(result.prefs.wallpaper_blur??18);
 applyContainerBackgroundOpacity(result.prefs.container_background_opacity??100);
 applyContainerBackgroundBlur(result.prefs.container_background_blur??18);
 applyMode();applyTheme();
 await applyWallpaper(result.prefs.wallpaper||'');
 S.containerWallpaper=result.prefs.container_wallpaper||'';
 await applyContainerWallpaper(S.containerWallpaper);
 const drive=await api('drive_status');
 if(await showDriveSetup(drive)){
  await api('sync');
  await refresh();
  $('status').textContent='Biblioteca local · Lista';
 }else{
  S.items=[];S.rows.clear();$('canvas').replaceChildren();updateSummary();
 }
 }finally{S.loading=false;scheduleDraw();}
}
async function selectDriveProfile(id){
 await flush();await api('profile',{id});
 tagCatalog=null;authorCatalog=null;
 S.covers.clear();coverCache.clear();S.courseCovers.clear();
 S.selected=null;S.bulkIds.clear();S.similarIds=null;S.tokens=[];S.libraryTokens=[];
 S.course=null;S.resources=[];S.coursePath=[];S.courseSelection=null;S.courseSelectedKeys.clear();
 importJobs.clear();setImportNotice('');$('importPanel').hidden=true;
 $('popover').hidden=true;popoverAnchor=null;hideTagSuggestions();
 $('details').hidden=true;$('courseInspector').hidden=true;$('inspectorEmpty').hidden=false;
 $('similar').hidden=true;$('similar').setAttribute('aria-pressed','false');
 setView('grid');
 await loadActiveProfile();
}
async function showDriveSetup(state){
 const view=$('setupView');view.hidden=state.state==='ready';if(view.hidden)return true;
 const labels={not_installed:['Instala Google Drive','Balisco necesita Google Drive para escritorio para leer tu biblioteca.'],not_running:['Inicia Google Drive','Espera a que Google Drive monte Mi unidad y vuelve a detectar la conexión.'],needs_profile:['Elige un perfil de Drive','Selecciona la cuenta que contiene tu biblioteca.'],needs_location:['Ubica tu biblioteca','Elige una carpeta existente dentro de Mi unidad o crea una nueva.'],needs_migration:['Vamos a organizar tus archivos','Tus libros y cursos están en las carpetas antiguas de Balisco. Revisa dónde quedará cada uno antes de continuar.']};
 const [title,description]=labels[state.state]||['Conectar biblioteca','Revisa la conexión con Google Drive.'];$('setupTitle').textContent=title;$('setupDescription').textContent=description;
 const actions=$('setupActions'),details=$('setupDetails'),accountPanel=$('setupAccount');actions.replaceChildren();details.replaceChildren();details.hidden=true;accountPanel.replaceChildren();accountPanel.hidden=true;view.classList.toggle('is-migration',state.state==='needs_migration');
 const add=(label,run,recheck=true)=>{const button=document.createElement('button');button.type='button';button.textContent=label;button.onclick=guard(async()=>{button.disabled=true;try{await run();if(recheck){const next=await api('drive_status');if(await showDriveSetup(next)){await api('sync');await refresh();}}}finally{button.disabled=false;}});actions.append(button);};
 const showAccountSwitch=()=>{
  accountPanel.hidden=false;accountPanel.replaceChildren();
  const button=document.createElement('button');button.type='button';button.className='setup-switch-account';button.textContent='Cambiar cuenta de Drive';accountPanel.append(button);
  button.onclick=guard(async()=>{
   button.disabled=true;const profiles=await api('profiles');accountPanel.replaceChildren();
   const title=document.createElement('p');title.textContent='Elige la cuenta de Drive que quieres usar:';accountPanel.append(title);
   for(const profile of profiles){const choice=document.createElement('button');choice.type='button';choice.className='setup-profile-choice';choice.textContent=`${profile.id}${profile.id===state.profile?' · Cuenta actual':''}${profile.error?' · No disponible':''}`;choice.disabled=!!profile.error||profile.id===state.profile;choice.onclick=guard(()=>selectDriveProfile(profile.id));accountPanel.append(choice);}
   const back=document.createElement('button');back.type='button';back.className='setup-switch-account';back.textContent='Volver';back.onclick=showAccountSwitch;accountPanel.append(back);
  });
 };
 if(state.state==='not_installed'){add('⬇ Instalar Google Drive',()=>api('drive_install'));add('🔄 Verificar instalación',async()=>{});}
 if(state.state==='not_running'){add('🚀 Iniciar Google Drive',()=>api('drive_start'));add('🔄 Detectar conexión',async()=>{});}
 if(state.state==='needs_profile')for(const id of state.profiles||[])add(id,()=>selectDriveProfile(id),false);
 if(state.state==='needs_location'){add('📁 Seleccionar carpeta existente',()=>api('library_pick'));add('➕ Crear carpeta nueva',async()=>{const name=prompt('Nombre de la nueva biblioteca','Biblioteca');if(name)await api('library_create',{name});});showAccountSwitch();}
 if(state.state==='needs_migration'){
  showAccountSwitch();
  details.hidden=false;details.innerHTML='<p class="setup-loading" role="status">Buscando tus archivos y preparando sus nuevas carpetas…</p>';
  let preview;try{preview=await api('migration_preview');}catch(error){details.innerHTML='';$('setupDescription').textContent=`No se pudo preparar la organización: ${error.message}`;add('Volver a revisar los archivos',()=>showDriveSetup(state),false);return false;}
  const count=preview.count;
  details.hidden=false;
  details.innerHTML=`<p class="setup-count">${count===1?'1 elemento por organizar':`${count} elementos por organizar`}</p><ol class="setup-steps"><li><strong>Revisa los destinos.</strong> Cada archivo irá a la carpeta de su primera etiqueta; los que no tengan etiquetas irán a <code>_Inbox</code>.</li><li><strong>Confirma el cambio.</strong> Balisco guardará en Drive una copia de tus datos, notas y portadas antes de mover los archivos.</li><li><strong>Abre tu biblioteca.</strong> Los archivos conservarán sus datos y podrás encontrarlos en sus nuevas carpetas.</li></ol><div id="setupMoveList" class="setup-move-list" hidden></div><p id="setupProgress" class="setup-progress" role="status"></p>`;
  const list=$('setupMoveList');
  const shortPath=path=>{const root=preview.root||'';return path.toLowerCase().startsWith(root.toLowerCase())?path.slice(root.length).replace(/^[/\\]/,''):path;};
  if(count){
   const heading=document.createElement('h2');heading.textContent='Así quedarán tus archivos';list.append(heading);
   const rows=document.createElement('div');rows.className='setup-move-rows';
   for(const move of preview.moves){const row=document.createElement('div');row.className='setup-move-row';const from=document.createElement('span');from.textContent=shortPath(move.from);const arrow=document.createElement('span');arrow.className='setup-move-arrow';arrow.textContent='→';const to=document.createElement('strong');to.textContent=shortPath(move.to);row.append(from,arrow,to);rows.append(row);}list.append(rows);
  }else{const empty=document.createElement('p');empty.textContent='Solo quedan carpetas antiguas vacías. Balisco las retirará después del respaldo.';list.append(empty);}
  add('Ver dónde quedarán mis archivos',async()=>{list.hidden=false;actions.replaceChildren();add('Crear respaldo y organizar ahora',async()=>{actions.querySelectorAll('button').forEach(button=>button.disabled=true);$('setupProgress').textContent='Creando respaldo y organizando archivos…';try{const result=await api('migration_run');$('setupProgress').textContent=`Listo: ${result.moved} ${result.moved===1?'elemento organizado':'elementos organizados'}. Abriendo tu biblioteca…`;}catch(error){$('setupProgress').textContent=`No se completó la organización: ${error.message}`;throw error;}});},false);
 }
 return false;
}
async function boot(){if(ready||typeof window.pywebview?.api?.call!=='function')return;ready=true;try{windowState((await api('window_state'))?.maximized);await loadActiveProfile();requestAnimationFrame(()=>requestAnimationFrame(()=>guard(()=>api('ready',{firstPaint:performance.now(),visibleCards:S.rows.size}))()));}catch(e){notify(e.message);$('summary').textContent='No se pudo conectar con la biblioteca';}}
window.addEventListener('pywebviewready',boot);
boot();
const bootPoll=setInterval(()=>{if(ready){clearInterval(bootPoll);return;}boot();},50);
setTimeout(()=>{clearInterval(bootPoll);if(!ready){$('summary').textContent='Vista previa · inicia python main.py para conectar';$('status').textContent='Sin conexión al escritorio';}},10000);
