import {icon} from './icons.js?v=9';
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const bytes=n=>n?`${(n/1024**(Math.min(3,Math.floor(Math.log(n)/Math.log(1024))))).toFixed(1)} ${['B','KB','MB','GB'][Math.min(3,Math.floor(Math.log(n)/Math.log(1024)))]}`:'—';
const states=['pendiente','interesado','leyendo','leido','abandonado'];
const defaultFilterStates=states.slice(1);
let filterStates=[...defaultFilterStates];try{const saved=JSON.parse(localStorage.getItem('balisco.stateOrder')||'null');if(Array.isArray(saved)&&saved.length===defaultFilterStates.length&&defaultFilterStates.every(x=>saved.includes(x)))filterStates=saved;}catch{}
const stateNames={pendiente:'Pendiente',interesado:'Interesado',leyendo:'Leyendo',leido:'Leído',abandonado:'Abandonado'};
const typeIcons={pdf:'document',curso:'course',video:'video'};
const S={items:[],tokens:[],selected:null,pinned:false,showOverlays:true,mode:'local',theme:'auto',zoom:195,wallpaper:'',wallpaperOpacity:24,wallpaperBlur:18,view:'grid',revision:0,selectionRevision:0,rows:new Map(),covers:new Map(),pending:new Map(),saving:Promise.resolve(),course:null,resources:[],resourceLimit:120,bulkMode:false,bulkIds:new Set()};
let toastTimer,drawFrame,ghostTimer,ready=false,keyboardCardId=null;
async function api(action,payload={}){if(!window.pywebview?.api)throw Error('Abre Balisco con python main.py para conectar la biblioteca.');const r=await window.pywebview.api.call(action,payload);if(!r.ok)throw Error(r.error);return r.data;}
function notify(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,5000);}
function guard(fn){return (...args)=>{try{return Promise.resolve(fn(...args)).catch(report);}catch(e){report(e);}};}
function report(e){if(e.message==='Preferencia inválida')return;notify(e.message);$('status').textContent='Revisa el aviso';}
function button(name,label,id){return `<button class="icon-button" id="${id}"${label?` title="${label}"`:''} aria-label="${label}">${icon(name)}</button>`;}
$('dock').innerHTML=button('refresh','Sincronizar biblioteca','sync')+button('user','Cambiar cuenta','profiles')+'<span class="divider"></span>'+button('tag','Explorar etiquetas','tags')+button('users','Explorar autores','authors')+button('multi','Etiquetado y autores masivos','bulk')+button('dice','','dice')+button('eye','Mostrar detalles sobre las portadas','overlays')+'<span class="divider"></span>'+button('heart','Mostrar solo favoritos','favorite')+button('status','Filtrar por estado','statusFilter')+button('star','Filtrar por calificación','rating')+button('filter','Filtrar por tipo','type')+'<span class="divider"></span>'+button('grid','Tamaño de la cuadrícula','zoom')+button('local','Modo de apertura: Local','mode')+'<span class="divider"></span>'+button('backup','Crear respaldo en Drive','backup')+button('wallpaper','Fondo de pantalla','wallpaper')+button('theme','Tema: automático','theme')+'<span class="divider"></span>'+button('winMin','Minimizar','winMin')+button('winMax','Maximizar','winMax')+button('winClose','Cerrar','winClose');
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
function applyOverlayVisibility(){document.body.classList.toggle('overlays-hidden',!S.showOverlays);for(const element of document.querySelectorAll('#canvas .badge,#heroBadge,#pin'))element.hidden=!S.showOverlays;const control=$('overlays');control.innerHTML=icon(S.showOverlays?'eye':'eyeOff');control.setAttribute('aria-pressed',String(S.showOverlays));control.title=S.showOverlays?'Ocultar detalles sobre las portadas':'Mostrar detalles sobre las portadas';control.setAttribute('aria-label',control.title);}
try{S.showOverlays=localStorage.getItem('balisco.showOverlays')!=='false';}catch{}
applyOverlayVisibility();
$('overlays').onclick=()=>{S.showOverlays=!S.showOverlays;applyOverlayVisibility();try{localStorage.setItem('balisco.showOverlays',String(S.showOverlays));}catch{}api('preference',{key:'show_overlays',value:String(S.showOverlays)}).catch(()=>{});};
function animateControl(button,className='control-feedback'){button.classList.remove(className);void button.offsetWidth;button.classList.add(className);}
$('dock').addEventListener('click',event=>{const control=event.target.closest('.icon-button');if(control)animateControl(control);},true);
function gridIcon(level){return `<svg viewBox="0 0 24 24" aria-hidden="true">${Array.from({length:4},(_,i)=>`<rect class="${i<level?'filled':''}" x="${3+(i%2)*11}" y="${3+Math.floor(i/2)*11}" width="7" height="7" rx="1"/>`).join('')}</svg>`;}
function updateGridIcon(columns,animate=false){const control=$('zoom');if(control.dataset.columns===String(columns))return;const {min,max}=zoomLevels(),level=Math.max(1,Math.min(4,columns-min+1));control.dataset.columns=String(columns);control.innerHTML=gridIcon(level);control.title=`Cuadrícula: ${columns} columnas · nivel ${level} de ${max-min+1}`;control.setAttribute('aria-label',control.title);if(animate)animateControl(control,'grid-change');}
$('dice').innerHTML=icon('dice','dice-art')+icon('target','target-art');
for(const [id,name] of [['pin','pin'],['driveOpen','drive'],['localOpen','folder']])$(id).innerHTML=icon(name);
document.querySelector('.empty-symbol').innerHTML=icon('book');
function art(item){const hue=[...item.drive_id].reduce((a,c)=>a+c.charCodeAt(0),0)%60+190;return `<div class="typography" style="--hue:${hue}"><div class="cover-category">${esc(item.categoria_macro||'Biblioteca')}</div><div class="cover-title">${esc(item.titulo.replace(/\.(pdf|epub)$/i,''))}</div><div class="cover-rule"></div></div>`;}
function setView(view){S.view=view;for(const [id,key] of [['viewport','grid'],['tagsView','tags'],['authorsView','authors'],['courseView','course']])$(id).hidden=view!==key;$('viewTitle')&&($('viewTitle').textContent=view==='tags'?'Etiquetas':view==='authors'?'Autores':view==='course'?(S.course?.titulo||'Curso'):'Biblioteca');$('eyebrow')&&($('eyebrow').textContent=view==='course'?'RECURSOS DE ESTUDIO':'TU ESPACIO DE CONOCIMIENTO');$('tags').setAttribute('aria-pressed',view==='tags');$('authors').setAttribute('aria-pressed',view==='authors');if(view==='grid')scheduleDraw();}
function updateSummary(){$('summary').textContent=S.items.length;}
function searchTokens(){const draft=$('ghost').hidden?'':$('ghost').value.trim();return draft&&!/^[+@-]/.test(draft)?[...S.tokens,draft]:S.tokens;}
async function refresh(reset=false,reuseCards=false){const rev=++S.revision;const result=await api('query',{tokens:searchTokens()});if(rev!==S.revision)return;S.items=result.items;if(!reuseCards){S.rows.clear();$('canvas').replaceChildren();}if(reset)$('viewport').scrollTop=0;renderFilters();updateSummary();scheduleDraw();}
function scheduleDraw(){if(!drawFrame)drawFrame=requestAnimationFrame(()=>{drawFrame=0;draw();});}
let zoomAnchor=null,zoomAnimatingUntil=0,zoomCleanupTimer=null;
function draw(){if(S.view!=='grid')return;const v=$('viewport'),width=v.clientWidth-56,gap=20,cols=Math.max(1,Math.floor((width+gap)/(S.zoom+gap))),w=(width-gap*(cols-1))/cols,h=Math.round(w*1.25)+65,stride=h+22;updateGridIcon(cols,performance.now()<zoomAnimatingUntil);$('canvas').style.height=`${Math.ceil(S.items.length/cols)*stride}px`;if(zoomAnchor){v.scrollTop=Math.floor(zoomAnchor.index/cols)*stride+zoomAnchor.fraction*stride;zoomAnchor=null;}const start=Math.max(0,Math.floor(v.scrollTop/stride)-1)*cols,end=Math.min(S.items.length,(Math.ceil((v.scrollTop+v.clientHeight)/stride)+1)*cols);
 const needed=new Set();for(let i=start;i<end;i++){const item=S.items[i];needed.add(item.drive_id);let node=S.rows.get(item.drive_id);if(!node){node=card(item);S.rows.set(item.drive_id,node);$('canvas').append(node);}node.dataset.index=i;node.style.width=w+'px';node.style.height=h+'px';node.style.transform=`translate3d(${(i%cols)*(w+gap)}px,${Math.floor(i/cols)*stride}px,0)`;node.classList.toggle('selected',S.selected?.drive_id===item.drive_id);node.classList.toggle('bulk-selected',S.bulkIds.has(item.drive_id));}
 if(performance.now()>=zoomAnimatingUntil)for(const [id,node] of S.rows)if(!needed.has(id)){node.remove();S.rows.delete(id);}
 $('empty').hidden=!!S.items.length;if(!S.items.length)$('empty').innerHTML='<h2>'+ (searchTokens().length?'Nada por aquí, todavía':'Tu biblioteca empieza aquí')+'</h2><p>'+(searchTokens().length?'Quita un filtro o prueba otro término.':'Sincroniza tu Biblioteca de Google Drive para empezar.')+'</p>';
}
async function focusCardIndex(index,updateSelection=true){
 const item=S.items[index];if(!item||S.view!=='grid')return;
 const v=$('viewport'),width=v.clientWidth-56,gap=20,cols=Math.max(1,Math.floor((width+gap)/(S.zoom+gap))),cardWidth=(width-gap*(cols-1))/cols,cardHeight=Math.round(cardWidth*1.25)+65,stride=cardHeight+22,top=16+Math.floor(index/cols)*stride,bottom=top+cardHeight;
 if(top<v.scrollTop+16)v.scrollTop=Math.max(0,top-16);
 else if(bottom>v.scrollTop+v.clientHeight-24)v.scrollTop=bottom-v.clientHeight+24;
 draw();S.rows.get(item.drive_id)?.focus({preventScroll:true});keyboardCardId=item.drive_id;
 if(updateSelection)await select(item.drive_id);
}
function card(item){const el=document.createElement('article'),authors=authorNames(item.autor);el.className='card';el.tabIndex=0;el.dataset.state=item.estado_lectura;el.setAttribute('aria-label',item.titulo+(item.es_favorito?', favorito':''));el.innerHTML=`<div class="cover">${art(item)}<span class="badge">${item.tipo==='curso'?'CURSO':item.tipo==='video'?'VIDEO':'LIBRO'}</span></div><div class="card-info"><div class="card-title">${esc(item.titulo)}</div><div class="card-meta">${item.es_favorito?`<span class="favorite-mark" title="Favorito">${icon('heart')}</span>`:''}${item.rating?icon('star')+' '+item.rating+' · ':''}${esc(bytes(item.tamano_bytes))}${authors.length?`<span class="card-author" title="${esc(authors.join(', '))}">· ${esc(authors[0])}${authors.length>1?' +'+(authors.length-1):''}</span>`:''}</div></div>`;
 el.onfocus=()=>{keyboardCardId=item.drive_id;};
 el.querySelector('.badge').hidden=!S.showOverlays;
 el.onclick=guard(()=>S.bulkMode?toggleBulkSelection(item.drive_id):select(item.drive_id));el.ondblclick=guard(()=>S.bulkMode?undefined:openItem(item));el.onkeydown=guard(e=>{if(e.target!==el)return;if(e.key==='Enter'){e.preventDefault();return S.bulkMode?toggleBulkSelection(item.drive_id):openItem(item);}if(e.key===' '){e.preventDefault();return S.bulkMode?toggleBulkSelection(item.drive_id):select(item.drive_id);}if(e.key==='F2'){e.preventDefault();el.querySelector('.state-button').focus();}});
 loadCover(item.drive_id).then(src=>{if(src&&el.isConnected){const img=new Image();img.src=src;img.decoding='async';img.alt='';el.querySelector('.cover').prepend(img);el.querySelector('.typography').hidden=true;}}).catch(()=>{});return el;}
let coverQueue=[],coverActive=0;
function loadCover(id){if(S.covers.has(id))return S.covers.get(id);const promise=new Promise((resolve,reject)=>{coverQueue.push({id,resolve,reject});pumpCovers();});S.covers.set(id,promise);if(S.covers.size>250)S.covers.delete(S.covers.keys().next().value);return promise;}
function pumpCovers(){while(coverActive<3&&coverQueue.length){const job=coverQueue.shift();coverActive++;api('cover',{id:job.id}).then(job.resolve,job.reject).finally(()=>{coverActive--;pumpCovers();});}}
function renderFilters(){
 $('filters').innerHTML=S.tokens.map((t,i)=>`<button class="chip ${t.startsWith('+')?'include':t.startsWith('-')?'exclude':t.startsWith('@')?'gold':''}" data-index="${i}" title="Quitar filtro ${esc(t)}">${esc(t)}${icon('close')}</button>`).join('');
 const favorite=S.tokens.includes('@favoritos');
 const state=[...S.tokens].reverse().find(t=>filterStates.includes(t.slice(1)))?.slice(1);
 const rating=[...S.tokens].reverse().find(t=>/^@rating:[1-5]$/.test(t));
 const type=[...S.tokens].reverse().find(t=>['pdf','curso','video'].includes(t.slice(6))&&t.startsWith('@tipo:'))?.slice(6);
 const labels={favorite:favorite?'Mostrar todos los libros':'Mostrar solo favoritos',statusFilter:state?'Estado: '+stateNames[state]:'Pendiente · todos los elementos',rating:rating?'Calificación: '+rating.slice(8)+' estrellas':'Filtrar por calificación',type:type?'Tipo: '+({pdf:'Libros',curso:'Cursos',video:'Videos'}[type]):'Filtrar por tipo'};
 for(const [id,active] of [['favorite',favorite],['statusFilter',!!state],['rating',!!rating],['type',!!type]]){
  const button=$(id);button.setAttribute('aria-pressed',String(active));button.title=labels[id];button.setAttribute('aria-label',labels[id]);
 }
 $('statusFilter').innerHTML=`<span class="state-indicator ${state||'all'}"></span>`;
 const fill=rating?Number(rating.slice(8))*20:0;
 $('rating').innerHTML=`<span class="rating-indicator">${icon('star')}<span class="rating-fill" style="width:${fill}%">${icon('star')}</span></span>`;
 $('type').innerHTML=icon(type?typeIcons[type]:'filter');
}
async function toggleFacet(prefix,token){
 const previous=[...S.tokens],current=S.tokens.find(value=>value.startsWith(prefix));
 S.tokens=S.tokens.filter(value=>!value.startsWith(prefix));
 if(current!==token)S.tokens.push(token);
 try{await flush();setView('grid');await refresh(true);}catch(e){S.tokens=previous;renderFilters();throw e;}
}
async function toggleFacetState(state){
 const previous=[...S.tokens],current=filterStates.find(value=>S.tokens.includes('@'+value));
 S.tokens=S.tokens.filter(value=>!filterStates.some(option=>value==='@'+option));
 if(current!==state)S.tokens.push('@'+state);
 try{await flush();setView('grid');await refresh(true);}catch(e){S.tokens=previous;renderFilters();throw e;}
}
async function addToken(token){token=token.trim();if(!token||S.tokens.includes(token))return;const previous=[...S.tokens];S.tokens.push(token);try{await flush();setView('grid');await refresh(true);}catch(e){S.tokens=previous;renderFilters();throw e;}}
let swiping=false,swipeTokens=new Set();
$('filters').onpointerdown=e=>{const el=e.target.closest('[data-index]');if(!el||e.button!==0)return;swiping=true;swipeTokens.add(S.tokens[+el.dataset.index]);el.style.opacity='.2';e.preventDefault();};
document.addEventListener('pointermove',e=>{if(!swiping)return;const el=document.elementFromPoint(e.clientX,e.clientY)?.closest('#filters [data-index]');if(el){swipeTokens.add(S.tokens[+el.dataset.index]);el.style.opacity='.2';}});
document.addEventListener('pointerup',guard(async()=>{if(!swiping)return;swiping=false;S.tokens=S.tokens.filter(t=>!swipeTokens.has(t));swipeTokens.clear();await refresh(true);}));
$('filters').onclick=guard(async e=>{if(e.detail!==0)return;const el=e.target.closest('[data-index]');if(el){S.tokens.splice(+el.dataset.index,1);await refresh(true);}else{ghostShow();}});
let tagCatalog=null,tagCatalogPromise=null,authorCatalog=null,authorCatalogPromise=null,tagMatches=[],tagSuggestionIndex=-1,tagSuggestionRevision=0;
const foldText=value=>String(value).normalize('NFD').replace(/\p{M}/gu,'').toLocaleLowerCase();
async function loadTagCatalog(){if(tagCatalog)return tagCatalog;if(!tagCatalogPromise)tagCatalogPromise=api('tags');try{tagCatalog=await tagCatalogPromise;return tagCatalog;}finally{tagCatalogPromise=null;}}
async function loadAuthorCatalog(){if(authorCatalog)return authorCatalog;if(!authorCatalogPromise)authorCatalogPromise=api('authors');try{authorCatalog=await authorCatalogPromise;return authorCatalog;}finally{authorCatalogPromise=null;}}
function hideTagSuggestions(){tagSuggestionRevision++;tagMatches=[];tagSuggestionIndex=-1;$('tagSuggestions').hidden=true;$('ghost').setAttribute('aria-expanded','false');$('ghost').removeAttribute('aria-activedescendant');}
async function updateTagSuggestions(){const text=$('ghost').value.trim();if($('ghost').hidden||!(['+','-'].includes(text[0])||text.toLowerCase().startsWith('autor:'))){hideTagSuggestions();return;}const revision=++tagSuggestionRevision;const menu=$('tagSuggestions');const isAuthor=text.toLowerCase().startsWith('autor:');const catalog=await (isAuthor?loadAuthorCatalog():loadTagCatalog());if(revision!==tagSuggestionRevision||$('ghost').hidden||$('ghost').value.trim()!==text)return;const needle=foldText(isAuthor?text.slice(6):text.slice(1));tagMatches=catalog.filter(item=>foldText(isAuthor?item.author:item.tag).includes(needle)).slice(0,8);tagSuggestionIndex=-1;$('ghost').removeAttribute('aria-activedescendant');menu.innerHTML=tagMatches.length?tagMatches.map((item,index)=>`<button type="button" id="tagSuggestion${index}" data-suggestion="${index}" role="option" aria-selected="false"><span>${esc(isAuthor?'autor:'+item.author:text[0]+item.tag)}</span><small>${item.total}</small></button>`).join(''):'<div class="suggestion-empty">Sin etiquetas coincidentes</div>';const rect=$('ghost').getBoundingClientRect();menu.style.left=rect.left+'px';menu.style.top=(rect.bottom+5)+'px';menu.style.width=rect.width+'px';menu.hidden=false;$('ghost').setAttribute('aria-expanded','true');}
function moveTagSuggestion(direction){if(!tagMatches.length)return;tagSuggestionIndex=tagSuggestionIndex<0?(direction>0?0:tagMatches.length-1):(tagSuggestionIndex+direction+tagMatches.length)%tagMatches.length;$('tagSuggestions').querySelectorAll('[data-suggestion]').forEach((button,index)=>{const active=index===tagSuggestionIndex;button.classList.toggle('active',active);button.setAttribute('aria-selected',String(active));});$('ghost').setAttribute('aria-activedescendant','tagSuggestion'+tagSuggestionIndex);}
function ghostShow(value){$('ghost').hidden=false;$('searchToggle').setAttribute('aria-expanded','true');if(value!==undefined)$('ghost').value=value;$('ghost').focus();setView('grid');if(value)queueSearch();}
function ghostHide(){clearTimeout(ghostTimer);hideTagSuggestions();$('ghost').value='';$('ghost').hidden=true;$('searchToggle').setAttribute('aria-expanded','false');}
function queueSearch(){clearTimeout(ghostTimer);guard(updateTagSuggestions)();ghostTimer=setTimeout(guard(()=>refresh(true,true)),70);}
$('searchToggle').onclick=guard(async()=>{if($('ghost').hidden)ghostShow();else{ghostHide();await refresh(true);}});
$('searchToggle').onpointerdown=e=>{if(!$('ghost').hidden)e.preventDefault();};
$('ghost').onblur=e=>{hideTagSuggestions();if(!$('ghost').value.trim()&&e.relatedTarget!==$('searchToggle')){ghostHide();guard(()=>refresh(true))();}};
$('tagSuggestions').onpointerdown=e=>e.preventDefault();
$('tagSuggestions').onclick=guard(async e=>{const option=e.target.closest('[data-suggestion]');if(option)await commitGhost($('ghost').value.toLowerCase().startsWith('autor:')?'autor:'+tagMatches[Number(option.dataset.suggestion)].author:$('ghost').value.trim()[0]+tagMatches[Number(option.dataset.suggestion)].tag);});
async function commitGhost(value){clearTimeout(ghostTimer);const text=(value??$('ghost').value).trim();if(!text)return;if(text==='+'||text==='-'||text==='@')return;ghostHide();$('searchToggle').focus();if(S.tokens.includes(text)){await refresh(true);return;}try{await addToken(text);}catch(error){ghostShow(text);throw error;}}
document.addEventListener('keydown',guard(async e=>{const editing=e.target instanceof Element && e.target.matches('input,textarea,select,[contenteditable=true]');if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='f'&&!$('dialog').open){e.preventDefault();ghostShow();return;}if(e.key==='Escape'){if($('dialog').open)return;if(!$('ghost').hidden){e.preventDefault();ghostHide();$('searchToggle').focus();await refresh(true);return;}if(editing){e.target.blur();return;}$('popover').hidden=true;S.tokens=[];await flush();setView('grid');await refresh(true);return;}if(editing||e.ctrlKey||e.metaKey||e.altKey||e.key.length!==1)return;if(e.key==='/'||/[\p{L}\p{N}+@-]/u.test(e.key)){e.preventDefault();ghostShow(e.key==='/'?'':e.key);}}));
$('ghost').onkeydown=guard(async e=>{if((e.key==='ArrowDown'||e.key==='ArrowUp')&&!$('tagSuggestions').hidden){e.preventDefault();moveTagSuggestion(e.key==='ArrowDown'?1:-1);}else if(e.key==='Enter'){e.preventDefault();const suggestion=tagSuggestionIndex>=0?($('ghost').value.toLowerCase().startsWith('autor:')?'autor:'+tagMatches[tagSuggestionIndex].author:$('ghost').value.trim()[0]+tagMatches[tagSuggestionIndex].tag):undefined;await commitGhost(suggestion);}else if(e.key==='Backspace'&&!$('ghost').value&&S.tokens.length){e.preventDefault();S.tokens.pop();await refresh(true);}});$('ghost').oninput=queueSearch;
function stars(container,value,callback){container.classList.add('stars');container.innerHTML=Array.from({length:5},(_,i)=>`<button class="${i<value?'on':''}" aria-label="${i+1} estrellas" title="${i+1} estrellas" data-rating="${i+1}">${icon('star')}</button>`).join('');container.onpointerover=e=>{const n=+e.target.closest('[data-rating]')?.dataset.rating;container.querySelectorAll('button').forEach((b,i)=>b.classList.toggle('preview',i<n));};container.onpointerleave=()=>container.querySelectorAll('button').forEach(b=>b.classList.remove('preview'));container.onclick=guard(e=>{const n=+e.target.closest('[data-rating]')?.dataset.rating;if(n)return callback(n);});}
let popoverAnchor=null;
function pop(anchor){const el=$('popover');if(!el.hidden&&popoverAnchor===anchor){el.hidden=true;popoverAnchor=null;return null;}popoverAnchor=anchor;el.replaceChildren();el.className='popover';el.hidden=false;el.style.right=Math.max(12,innerWidth-anchor.getBoundingClientRect().right)+'px';return el;}
$('rating').onclick=()=>{const el=pop($('rating'));if(!el)return;stars(el,0,async n=>{$('popover').hidden=true;popoverAnchor=null;await toggleFacet('@rating:','@rating:'+n);});};
$('favorite').onclick=guard(async()=>{await flush();if(S.tokens.includes('@favoritos')){S.tokens=S.tokens.filter(token=>token!=='@favoritos');setView('grid');await refresh(true);}else await addToken('@favoritos');});
$('statusFilter').onclick=()=>{const el=pop($('statusFilter'));if(!el)return;const current=[...S.tokens].reverse().find(token=>filterStates.some(state=>token==='@'+state));el.classList.add('state-popover');el.innerHTML=`<button class="state-choice" data-reading="" title="Pendiente · todos los elementos" aria-label="Pendiente · todos los elementos" ${current?'':'aria-current="true"'}><span class="state-indicator all"></span></button>`+filterStates.map(state=>`<button class="state-choice" draggable="true" data-reading="${state}" title="${stateNames[state]}" aria-label="${stateNames[state]}" ${current==='@'+state?'aria-current="true"':''}><span class="state-indicator ${state}"></span></button>`).join('');let draggedState=null,wasDragging=false;
 el.ondragstart=event=>{const choice=event.target.closest('[data-reading]');if(!choice?.dataset.reading){event.preventDefault();return;}draggedState=choice.dataset.reading;wasDragging=true;event.dataTransfer.effectAllowed='move';};
 el.ondragover=event=>{if(draggedState&&event.target.closest('[data-reading]'))event.preventDefault();};
 el.ondrop=event=>{event.preventDefault();const target=event.target.closest('[data-reading]')?.dataset.reading;if(!draggedState||!target||target===draggedState)return;filterStates=filterStates.filter(x=>x!==draggedState);filterStates.splice(filterStates.indexOf(target),0,draggedState);localStorage.setItem('balisco.stateOrder',JSON.stringify(filterStates));const buttons=[...el.querySelectorAll('[data-reading]')];for(const state of filterStates){const button=buttons.find(x=>x.dataset.reading===state);el.append(button);}draggedState=null;};
 el.ondragend=()=>{draggedState=null;setTimeout(()=>{wasDragging=false;},0);};
 el.onclick=guard(async event=>{if(wasDragging)return;const option=event.target.closest('[data-reading]');if(!option)return;const state=option.dataset.reading;el.hidden=true;popoverAnchor=null;if(state)await toggleFacetState(state);else{S.tokens=S.tokens.filter(token=>!filterStates.some(value=>token==='@'+value));await flush();setView('grid');await refresh(true);}});};
$('type').onclick=()=>{const el=pop($('type'));if(!el)return;el.classList.add('type-popover');el.innerHTML=[['document','Libros','pdf'],['course','Cursos','curso'],['video','Videos','video']].map(([i,t,v])=>`<button class="type-choice" data-type="${v}" title="${t}" aria-label="${t}" ${S.tokens.includes('@tipo:'+v)?'aria-current="true"':''}>${icon(i)}</button>`).join('');el.onclick=guard(async e=>{const type=e.target.closest('[data-type]')?.dataset.type;if(type){el.hidden=true;popoverAnchor=null;await toggleFacet('@tipo:','@tipo:'+type);}});};
function wheelFacet(id,step){
 const state=[...S.tokens].reverse().find(t=>filterStates.includes(t.slice(1)))?.slice(1);
 const rating=[...S.tokens].reverse().find(t=>/^@rating:[1-5]$/.test(t));
 const type=[...S.tokens].reverse().find(t=>t.startsWith('@tipo:')&&['pdf','curso','video'].includes(t.slice(6)))?.slice(6);
 if(id==='favorite')return toggleFacet('@favoritos','@favoritos');
 if(id==='statusFilter'){
  const index=Math.max(0,filterStates.indexOf(state)+1),next=Math.max(0,Math.min(filterStates.length,index+step));
  if(next===index)return;
  if(next===0){S.tokens=S.tokens.filter(t=>!filterStates.some(value=>t==='@'+value));return flush().then(()=>{setView('grid');return refresh(true);});}
  return toggleFacetState(filterStates[next-1]);
 }
 if(id==='rating'){
  const index=rating?Number(rating.slice(8)):0,next=Math.max(0,Math.min(5,index+step));
  if(next===index)return;
  if(next===0){S.tokens=S.tokens.filter(t=>!t.startsWith('@rating:'));return flush().then(()=>{setView('grid');return refresh(true);});}
  return toggleFacet('@rating:','@rating:'+next);
 }
 const types=['pdf','curso','video'],index=type?types.indexOf(type)+1:0,next=Math.max(0,Math.min(types.length,index+step));
 if(next===index)return;
 if(next===0){S.tokens=S.tokens.filter(t=>!t.startsWith('@tipo:'));return flush().then(()=>{setView('grid');return refresh(true);});}
 return toggleFacet('@tipo:','@tipo:'+types[next-1]);
}
for(const id of ['favorite','statusFilter','rating','type'])$(id).addEventListener('wheel',e=>{
 e.preventDefault();if(!e.deltaY)return;guard(()=>wheelFacet(id,e.deltaY<0?1:-1))();
},{passive:false});
document.addEventListener('pointerdown',e=>{if(!e.target.closest('#popover,#rating,#type,#statusFilter,#wallpaper')){$('popover').hidden=true;popoverAnchor=null;}});
function updateBulkButton(){const button=$('bulk');button.setAttribute('aria-pressed',String(S.bulkMode));button.title=S.bulkMode?`Edición masiva: ${S.bulkIds.size} libros seleccionados · clic para terminar`:'Etiquetado y autores masivos';button.setAttribute('aria-label',button.title);const notice=$('bulkNotice');if(notice)notice.textContent=S.bulkMode?`${S.bulkIds.size} libros seleccionados · Cambia autores y etiquetas para todos`:'';}
async function toggleBulkSelection(id){const item=S.items.find(value=>value.drive_id===id);if(!item||item.tipo!=='pdf'){notify('La edición masiva solo admite libros.');return;}if(S.bulkIds.has(id)){S.bulkIds.delete(id);if(S.selected?.drive_id===id){const last=[...S.bulkIds].at(-1);if(last)await select(last,true);else{S.selected=null;$('details').hidden=true;$('inspectorEmpty').hidden=false;}}}else{S.bulkIds.add(id);await select(id,true);}updateBulkButton();scheduleDraw();}
async function bulkMetadata(field,operation,value){await flush();if(!S.bulkIds.size)throw Error('Selecciona al menos un libro.');const ids=[...S.bulkIds];const result=await api('bulk_metadata',{ids,field,operation,value});if(field==='autor')authorCatalog=null;else tagCatalog=null;if(S.selected&&S.bulkIds.has(S.selected.drive_id)){S.selected=await api('detail',{id:S.selected.drive_id});renderDetail(S.selected);}await refresh(false);updateBulkButton();notify(`${result.updated} libros actualizados`);}
$('bulk').onclick=guard(async()=>{await flush();S.bulkMode=!S.bulkMode;if(!S.bulkMode)S.bulkIds.clear();else{S.selected=null;$('details').hidden=true;$('inspectorEmpty').hidden=false;}setView('grid');updateBulkButton();scheduleDraw();});
async function select(id,force=false){if(S.pinned&&S.selected&&!force)return;const revision=++S.selectionRevision;await flush();const item=await api('detail',{id});if(revision!==S.selectionRevision)return;S.selected=item;renderDetail(item);scheduleDraw();}
function authorNames(value){return String(value||'').split(/\r?\n/).map(name=>name.trim()).filter(Boolean);}
function resizeDetailTitle(){const title=$('title');title.style.height='auto';title.style.height=Math.min(126,Math.max(54,title.scrollHeight))+'px';}
function renderDetail(item){$('inspectorEmpty').hidden=true;$('details').hidden=false;$('title').value=item.titulo;resizeDetailTitle();$('notes').value=item.notas;$('driveUrl').textContent=item.url;$('readingState').value=item.estado_lectura;$('heroBadge').textContent=item.tipo.toUpperCase();$('heroArt').innerHTML=art(item);$('saveState').textContent='';updateBulkButton();loadCover(item.drive_id).then(src=>{if(src&&S.selected?.drive_id===item.drive_id)$('heroArt').innerHTML=`<img src="${src}" alt="Portada">`;}).catch(report);
 const tags=item.etiquetas.split(/\s+/).filter(Boolean);$('itemTags').innerHTML=tags.map(t=>`<button class="tag" data-tag="${esc(t)}" title="Filtrar ${esc(t)}; clic derecho para quitar">${esc(t)}</button>`).join('')+`<button class="tag" id="addTag" aria-label="Añadir etiqueta">${icon('plus')}</button>`;
 $('addTag').onclick=()=>{$('tagForm').hidden=false;$('tagInput').focus();};$('tagForm').hidden=true;
 $('itemAuthors').innerHTML=authorNames(item.autor).map((name,index)=>`<span class="author-chip"><span title="${esc(name)}">${esc(name)}</span><button type="button" data-author-remove="${index}" aria-label="Quitar autor ${esc(name)}" title="Quitar autor">${icon('close')}</button></span>`).join('')+`<button type="button" class="tag" id="addAuthor" aria-label="Añadir autor" title="Añadir autor">${icon('plus')}</button>`;
 $('addAuthor').onclick=()=>{$('authorForm').hidden=false;$('authorInput').focus();};$('authorForm').hidden=true;$('authorInput').value='';
 $('itemFavorite').innerHTML=icon('heart');$('itemFavorite').setAttribute('aria-pressed',String(!!item.es_favorito));$('itemFavorite').setAttribute('aria-label',item.es_favorito?'Quitar de favoritos':'Marcar como favorito');$('itemFavorite').title=$('itemFavorite').getAttribute('aria-label');
 stars($('itemRating'),item.rating,n=>saveNow('rating',n===S.selected.rating?0:n));
 const date=item.fecha_agregado?new Date(item.fecha_agregado.replace(' ','T')+'Z').toLocaleDateString('es-PE'): '—';
 $('properties').innerHTML=[['Tamaño',bytes(item.tamano_bytes)],['Tipo',item.tipo.toUpperCase()],['Añadido',date],['Páginas / dimensiones','No disponibles']].map(([label,value])=>`<div class="property"><span>${label}</span><span>${esc(value)}</span></div>`).join('');}
function queueSave(field,value){if(!S.selected)return;const id=S.selected.drive_id,key=id+':'+field,previous=S.pending.get(key);if(previous)clearTimeout(previous.timer);const change={id,field,value};change.timer=setTimeout(()=>guard(()=>flush())(),500);S.pending.set(key,change);$('saveState').textContent='Guardando…';}
async function flush(){const edits=[...S.pending.entries()];for(const [,edit]of edits)clearTimeout(edit.timer);for(const [key]of edits)S.pending.delete(key);if(!edits.length)return S.saving;
 const work=async()=>{for(const [key,edit]of edits){try{const item=await api('update',edit);if(S.selected?.drive_id===edit.id){S.selected={...S.selected,[edit.field]:item[edit.field]};$('saveState').textContent='Guardado';}const card=S.items.find(i=>i.drive_id===edit.id);if(card)Object.assign(card,{[edit.field]:item[edit.field]});}catch(e){for(const [pendingKey,pendingEdit] of edits.slice(edits.findIndex(([k])=>k===key)))if(!S.pending.has(pendingKey))S.pending.set(pendingKey,pendingEdit);$('saveState').textContent='Sin guardar';throw e;}}};S.saving=S.saving.catch(()=>{}).then(work);await S.saving;}
async function saveNow(field,value){queueSave(field,value);await flush();if(field==='etiquetas')tagCatalog=null;if(field==='autor')authorCatalog=null;if(S.selected)renderDetail(S.selected);await refresh();}
$('title').oninput=()=>{resizeDetailTitle();queueSave('titulo',$('title').value);};$('notes').oninput=()=>queueSave('notas',$('notes').value);
for(const id of ['title','notes'])$(id).onblur=guard(async()=>{await flush();await refresh();});
$('readingState').onchange=guard(()=>saveNow('estado_lectura',$('readingState').value));
$('itemFavorite').onclick=guard(()=>saveNow('es_favorito',S.selected.es_favorito?0:1));
$('itemAuthors').onclick=guard(async event=>{const remove=event.target.closest('[data-author-remove]');if(!remove||!S.selected)return;const names=authorNames(S.selected.autor);if(S.bulkMode){await bulkMetadata('autor','remove',names[Number(remove.dataset.authorRemove)]);return;}names.splice(Number(remove.dataset.authorRemove),1);await saveNow('autor',names.join('\n'));$('addAuthor')?.focus();});
$('authorForm').onsubmit=guard(async event=>{event.preventDefault();if(!S.selected)return;const name=$('authorInput').value.trim().replace(/\s+/g,' ');if(!name)return;if(S.bulkMode){await bulkMetadata('autor','add',name);$('authorInput').value='';return;}const names=authorNames(S.selected.autor);if(!names.some(existing=>existing.toLocaleLowerCase()===name.toLocaleLowerCase())){names.push(name);await saveNow('autor',names.join('\n'));$('addAuthor')?.focus();}else{$('authorInput').select();}});
$('itemTags').onclick=guard(e=>{const tag=e.target.closest('[data-tag]')?.dataset.tag;if(tag)return addToken(tag);});$('itemTags').oncontextmenu=guard(async e=>{const tag=e.target.closest('[data-tag]')?.dataset.tag;if(tag){e.preventDefault();if(S.bulkMode)await bulkMetadata('etiquetas','remove',tag);else await saveNow('etiquetas',S.selected.etiquetas.split(/\s+/).filter(t=>t!==tag).join(' '));}});
$('tagForm').onsubmit=guard(async e=>{e.preventDefault();const text=$('tagInput').value.trim();if(text){if(S.bulkMode)await bulkMetadata('etiquetas','add',text);else await saveNow('etiquetas',S.selected.etiquetas+' '+text);$('tagInput').value='';}});
$('pin').onclick=()=>{S.pinned=!S.pinned;$('pin').setAttribute('aria-pressed',S.pinned);$('pin').title=S.pinned?'Desanclar inspector':'Anclar inspector';};
$('driveOpen').onclick=guard(async()=>{await flush();const result=await api('open',{id:S.selected.drive_id,mode:'web'});if(!result)throw Error('No se pudo abrir Google Drive.');});
$('localOpen').onclick=guard(async()=>{await flush();await api('reveal',{id:S.selected.drive_id});});
async function importCover(file){if(!file||!S.selected)return;if(!['image/jpeg','image/png','image/webp'].includes(file.type))throw Error('Selecciona una imagen JPG, PNG o WEBP.');if(file.size>12_000_000)throw Error('La portada debe pesar menos de 12 MB.');const id=S.selected.drive_id;const data=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result.split(',')[1]);r.onerror=reject;r.readAsDataURL(file);});await api('save_cover',{id,data});S.covers.delete(id);if(S.selected?.drive_id===id)renderDetail(S.selected);S.rows.get(id)?.remove();S.rows.delete(id);scheduleDraw();notify('Portada actualizada');}
$('hero').ondblclick=guard(()=>S.selected&&openItem(S.selected));$('hero').onkeydown=guard(e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();if(S.selected)return openItem(S.selected);}if(e.key==='F2'){e.preventDefault();$('coverFile').click();}});$('hero').oncontextmenu=e=>{e.preventDefault();$('coverFile').click();};$('coverFile').onchange=guard(async e=>{const file=e.target.files[0];e.target.value='';await importCover(file);});$('hero').ondragover=e=>{e.preventDefault();$('hero').classList.add('dragging');};$('hero').ondragleave=()=>$('hero').classList.remove('dragging');$('hero').ondrop=guard(async e=>{e.preventDefault();$('hero').classList.remove('dragging');await importCover(e.dataTransfer.files[0]);});
document.addEventListener('dragover',e=>e.preventDefault());document.addEventListener('drop',e=>e.preventDefault());
async function openItem(item){await flush();if(item.tipo==='curso'&&S.mode==='local'){S.course=item;$('courseName').textContent=item.titulo;$('courseName').title=item.titulo;setView('course');$('summary').textContent='Leyendo recursos…';$('resources').replaceChildren();S.resources=await api('course',{id:item.drive_id});S.resourceLimit=120;renderResources();}else{if(!await api('open',{id:item.drive_id,mode:S.mode}))throw Error('No se pudo abrir el elemento.');}}
function renderResources(){$('summary').textContent=S.resources.length+' recursos';$('resources').innerHTML=S.resources.slice(0,S.resourceLimit).map(r=>`<div class="resource"><div class="resource-name">${icon(r.mime?.startsWith('video/')?'video':'document')}<span title="${esc(r.title)}">${esc(r.title)}</span></div><small>${bytes(r.size)}</small><div>${button('play','Abrir recurso','open-'+r.id).replace('id=','data-open=')}${button('trash','Mover recurso a papelera','trash-'+r.id).replace('id=','data-trash=')}</div></div>`).join('');$('moreResources').hidden=S.resourceLimit>=S.resources.length;}
$('resources').onclick=guard(async e=>{const launch=e.target.closest('[data-open]'),trash=e.target.closest('[data-trash]');if(launch)await api('course_open',{course:S.course.drive_id,id:launch.dataset.open.slice(5),mode:S.mode});if(trash){const id=trash.dataset.trash.slice(6),resource=S.resources.find(r=>r.id===id);$('dialogTitle').textContent='Mover a la papelera';$('dialogBody').replaceChildren();const desc=document.createElement('p');desc.textContent=resource.title;const confirm=document.createElement('button');confirm.className='text-button';confirm.textContent='Mover a la papelera';confirm.onclick=guard(async()=>{await api('course_trash',{course:S.course.drive_id,id});S.resources=S.resources.filter(r=>r.id!==id);renderResources();$('dialog').close();});$('dialogBody').append(desc,confirm);$('dialog').showModal();}});
$('back').innerHTML=icon('back');$('explorer').innerHTML=icon('folder');
$('filters').addEventListener('wheel',e=>{const el=e.currentTarget;if(el.scrollWidth<=el.clientWidth)return;const delta=Math.abs(e.deltaY)>Math.abs(e.deltaX)?e.deltaY:e.deltaX;if(!delta)return;e.preventDefault();el.scrollLeft+=delta;},{passive:false});
$('moreResources').onclick=()=>{S.resourceLimit+=120;renderResources();};$('explorer').onclick=guard(()=>api('open',{id:S.course.drive_id,mode:'local'}));$('back').onclick=guard(async()=>{setView('grid');updateSummary();});$('home')?.addEventListener('click',guard(async()=>{await flush();setView('grid');await refresh();}));
$('tags').onclick=guard(async()=>{await flush();if(S.view==='tags'){setView('grid');updateSummary();return;}setView('tags');const tags=await api('tags');$('tagsView').innerHTML=tags.length?tags.map(t=>`<button class="tag-tile" data-tag="${esc(t.tag)}"><span>#${esc(t.tag)}</span><small>${t.total}</small></button>`).join(''):'<p>Añade etiquetas desde el inspector para empezar.</p>';});$('tagsView').onclick=guard(e=>{const t=e.target.closest('[data-tag]')?.dataset.tag;if(t)return addToken('+'+t);});
$('authors').onclick=guard(async()=>{await flush();if(S.view==='authors'){setView('grid');updateSummary();return;}setView('authors');const authors=await api('authors');$('authorsView').innerHTML=authors.length?authors.map(a=>`<button class="tag-tile" data-author="${esc(a.author)}"><span>${esc(a.author)}</span><small>${a.total}</small></button>`).join(''):'<p>Añade autores desde el inspector para empezar.</p>';});$('authorsView').onclick=guard(e=>{const name=e.target.closest('[data-author]')?.dataset.author;if(name)return addToken('autor:'+name);});
function applyMode(){$('mode').innerHTML=icon(S.mode==='web'?'web':'local');$('mode').title='Modo de apertura: '+S.mode;const ml=$('modeLabel');if(ml)ml.textContent=S.mode==='web'?'Web':'Local';}
$('mode').onclick=guard(async()=>{S.mode=S.mode==='local'?'web':'local';applyMode();await api('preference',{key:'modo',value:S.mode});});
function applyTheme(){document.documentElement.dataset.theme=S.theme==='auto'?(matchMedia('(prefers-color-scheme:light)').matches?'light':'dark'):S.theme;const control=$('theme');control.dataset.mode=S.theme;const themeIcon=S.theme==='auto'?'theme':S.theme==='dark'?'themeDark':'themeLight';control.innerHTML=icon(themeIcon,themeIcon);control.title='Tema: '+S.theme;control.setAttribute('aria-label',control.title);}
$('theme').onclick=guard(async()=>{S.theme=['auto','dark','light'][(['auto','dark','light'].indexOf(S.theme)+1)%3];applyTheme();animateControl($('theme'),'theme-change');await api('preference',{key:'tema',value:S.theme});});matchMedia('(prefers-color-scheme:light)').addEventListener('change',applyTheme);
document.addEventListener('pointercancel',()=>{swiping=false;swipeTokens.clear();renderFilters();});
let diceContextual=false;
function updateDiceUI(){
 $('dice').classList.toggle('target',diceContextual);
 $('dice').removeAttribute('title');
 $('dice').setAttribute('aria-label',diceContextual?'Descubrir según intereses recientes. Rueda o clic derecho para cambiar.':'Descubrir aleatoriamente. Rueda o clic derecho para cambiar.');
}
updateDiceUI();
$('dice').addEventListener('wheel',e=>{e.preventDefault();diceContextual=!diceContextual;updateDiceUI();},{passive:false});
$('dice').addEventListener('contextmenu',e=>{e.preventDefault();diceContextual=!diceContextual;updateDiceUI();});
$('dice').onclick=guard(async()=>{
 $('dice').classList.remove('spinning');
 void $('dice').offsetWidth;
 $('dice').classList.add('spinning');
 setTimeout(()=>$('dice').classList.remove('spinning'),700);
 await flush();
 const item=await api('random',{contextual:diceContextual});
 if(!item)return;
 S.tokens=[];setView('grid');await refresh();await select(item.drive_id,true);
 const i=S.items.findIndex(r=>r.drive_id===item.drive_id),v=$('viewport'),w=v.clientWidth-56,c=Math.max(1,Math.floor((w+20)/(S.zoom+20))),cw=(w-20*(c-1))/c;
 v.scrollTop=Math.floor(i/c)*(Math.round(cw*1.25)+87);
 scheduleDraw();
});
let zoomTimer=null;
function zoomLevels(){const width=$('viewport').clientWidth-56,gap=20,min=Math.max(1,Math.ceil((width+gap)/(430+gap))),max=Math.max(min,Math.min(min+3,Math.floor((width+gap)/(100+gap))));return {width,gap,min,max};}
function changeZoom(direction,wrap=false){const {width,gap,min,max}=zoomLevels(),total=width+gap,current=Math.max(min,Math.min(max,Math.floor(total/(S.zoom+gap))));let columns=current-direction;if(columns<min)columns=wrap?max:min;if(columns>max)columns=wrap?min:max;if(columns===current)return;const v=$('viewport'),oldWidth=(width-gap*(current-1))/current,oldStride=Math.round(oldWidth*1.25)+87,firstRow=Math.floor(v.scrollTop/oldStride);zoomAnchor={index:firstRow*current,fraction:(v.scrollTop-firstRow*oldStride)/oldStride};const upper=total/columns-gap,lower=total/(columns+1)-gap;S.zoom=Math.max(100,Math.min(430,Math.round((upper+lower)/2)));updateGridIcon(columns,true);zoomAnimatingUntil=performance.now()+260;clearTimeout(zoomCleanupTimer);zoomCleanupTimer=setTimeout(scheduleDraw,280);scheduleDraw();clearTimeout(zoomTimer);zoomTimer=setTimeout(()=>api('preference',{key:'zoom',value:S.zoom}).catch(error=>{if(error.message!=='Zoom inválido')report(error);}),350);}
function cycleZoom(){changeZoom(1,true);}
$('zoom').onclick=guard(cycleZoom);
$('zoom').addEventListener('wheel',e=>{e.preventDefault();changeZoom(e.deltaY<0?1:-1);},{passive:false});
document.addEventListener('wheel',e=>{
 if(!e.ctrlKey||e.target.closest('#zoom'))return;
 e.preventDefault();
 changeZoom(e.deltaY<0?1:-1);
},{passive:false});
$('backup').onclick=guard(async()=>{await flush();$('backup').disabled=true;$('status').textContent='Creando respaldo…';try{await api('backup');notify('Respaldo guardado en Drive');$('status').textContent='Respaldo completado';}finally{$('backup').disabled=false;}});
async function applyWallpaper(filename){S.wallpaper=filename||'';const backdrop=$('wallpaperBackdrop');if(!S.wallpaper){document.body.classList.remove('has-wallpaper');backdrop.style.backgroundImage='none';return;}try{const src=await api('get_wallpaper',{filename:S.wallpaper});if(src){backdrop.style.backgroundImage=`url("${src}")`;document.body.classList.add('has-wallpaper');}else{document.body.classList.remove('has-wallpaper');backdrop.style.backgroundImage='none';}}catch(e){document.body.classList.remove('has-wallpaper');backdrop.style.backgroundImage='none';}}
function applyWallpaperOpacity(value){S.wallpaperOpacity=Math.max(0,Math.min(100,Number(value)||0));document.documentElement.style.setProperty('--wallpaper-dim',String((100-S.wallpaperOpacity)/100));}
function applyWallpaperBlur(value){S.wallpaperBlur=Math.max(0,Math.min(30,Number(value)||0));document.documentElement.style.setProperty('--wallpaper-blur',S.wallpaperBlur+'px');}
function setupWallpaperDualControl(menu){
 const track=menu.querySelector('.wallpaper-dual');
 const thumbs={opacity:track.querySelector('[data-setting=opacity]'),blur:track.querySelector('[data-setting=blur]')};
 const value=setting=>setting==='opacity'?S.wallpaperOpacity:S.wallpaperBlur;
 const max=setting=>setting==='opacity'?100:30;
 function render(){const half=(track.clientWidth-34)/2;for(const setting of ['blur','opacity']){const thumb=thumbs[setting],position=setting==='blur'?8+half*value(setting)/max(setting):26+half+half*value(setting)/max(setting);thumb.style.left=`${position}px`;thumb.setAttribute('aria-valuenow',String(value(setting)));}track.style.setProperty('--range-left',thumbs.blur.style.left);track.style.setProperty('--range-right',thumbs.opacity.style.left);}
 function update(setting,next){if(setting==='opacity')applyWallpaperOpacity(Math.round(next));else applyWallpaperBlur(Math.round(next));render();}
 function save(setting){return api('preference',{key:setting==='opacity'?'wallpaper_opacity':'wallpaper_blur',value:value(setting)});}
 function pointerValue(event,setting){const rect=track.getBoundingClientRect(),half=(rect.width-34)/2,x=event.clientX-rect.left;return setting==='blur'?Math.max(0,Math.min(1,(x-8)/half))*30:Math.max(0,Math.min(1,(x-26-half)/half))*100;}
 let dragging=null;
 track.onpointerdown=event=>{if(event.button!==0)return;const direct=event.target.closest('.wallpaper-thumb')?.dataset.setting;if(direct)dragging=direct;else{const x=event.clientX-track.getBoundingClientRect().left;dragging=Math.abs(x-parseFloat(thumbs.opacity.style.left))<=Math.abs(x-parseFloat(thumbs.blur.style.left))?'opacity':'blur';}track.setPointerCapture(event.pointerId);update(dragging,pointerValue(event,dragging));event.preventDefault();};
 track.onpointermove=event=>{if(dragging)update(dragging,pointerValue(event,dragging));};
 const finish=guard(async()=>{if(!dragging)return;const setting=dragging;dragging=null;await save(setting);});
 track.onpointerup=finish;track.onpointercancel=finish;
 for(const setting of ['opacity','blur'])thumbs[setting].onkeydown=guard(async event=>{const step=event.key==='ArrowRight'||event.key==='ArrowUp'?1:event.key==='ArrowLeft'||event.key==='ArrowDown'?-1:0;if(!step)return;event.preventDefault();update(setting,value(setting)+step);await save(setting);});
 render();
}
$('wallpaper').onclick=guard(async()=>{const el=pop($('wallpaper'));if(!el)return;el.classList.add('wallpaper-popover');el.innerHTML='<div class="wallpaper-head">FONDO DE PANTALLA</div><p style="font-size:10px;color:var(--muted);padding:8px">Cargando fondos…</p>';const list=await api('wallpapers_list');el.innerHTML=`<div class="wallpaper-head"><span>FONDO DE PANTALLA</span><div class="wallpaper-dual"><button type="button" class="wallpaper-thumb" data-setting="blur" role="slider" aria-label="Desenfoque del fondo de pantalla" aria-valuemin="0" aria-valuemax="30"></button><button type="button" class="wallpaper-thumb" data-setting="opacity" role="slider" aria-label="Opacidad del fondo de pantalla" aria-valuemin="0" aria-valuemax="100"></button></div></div><div class="wallpaper-list"><button class="wallpaper-item none ${!S.wallpaper?'active':''}" data-wp="" title="Predeterminado sin fondo"><span>⊘ Sin fondo</span></button>${list.map(w=>`<button class="wallpaper-item ${S.wallpaper===w.filename?'active':''}" data-wp="${esc(w.filename)}" title="${esc(w.name)}"><span>${esc(w.name)}</span></button>`).join('')}</div><button class="wallpaper-upload" id="uploadWp">+ Añadir imagen…</button>`;setupWallpaperDualControl(el);for(const item of list){api('get_wallpaper',{filename:item.filename}).then(src=>{const btn=el.querySelector(`[data-wp="${CSS.escape(item.filename)}"]`);if(btn&&src){const img=document.createElement('img');img.src=src;img.alt=item.name;btn.prepend(img);}}).catch(()=>{});}el.onclick=guard(async e=>{const uploadBtn=e.target.closest('#uploadWp');if(uploadBtn){$('wallpaperFile').click();return;}const wpBtn=e.target.closest('[data-wp]');if(wpBtn){const selected=wpBtn.dataset.wp;await api('preference',{key:'wallpaper',value:selected});await applyWallpaper(selected);el.hidden=true;popoverAnchor=null;notify(selected?'Fondo de pantalla aplicado':'Fondo predeterminado');}});});
$('wallpaperFile').onchange=guard(async e=>{const file=e.target.files?.[0];if(!file)return;if(!['image/jpeg','image/png','image/webp'].includes(file.type))throw Error('Usa formatos JPG, PNG o WEBP');if(file.size>20_000_000)throw Error('La imagen no debe superar los 20 MB');$('status').textContent='Guardando fondo de pantalla…';const data=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result.split(',')[1]);r.onerror=reject;r.readAsDataURL(file);});const res=await api('save_wallpaper',{name:file.name,data});await applyWallpaper(res.filename);$('popover').hidden=true;notify('Fondo de pantalla guardado y aplicado');$('status').textContent='Fondo aplicado';});
$('sync').onclick=guard(async()=>{await flush();$('sync').disabled=true;$('status').textContent='Sincronizando…';try{const result=await api('sync');tagCatalog=null;authorCatalog=null;await refresh();$('status').textContent=result.indexados+' piezas sincronizadas';}finally{$('sync').disabled=false;}});
$('profiles').onclick=guard(async()=>{await flush();$('dialogTitle').textContent='Cuenta de Google Drive';$('dialogBody').textContent='Buscando cuentas…';$('dialog').showModal();const profiles=await api('profiles');$('dialogBody').innerHTML=profiles.map(p=>`<button class="text-button profile-choice" data-profile="${esc(p.id)}" ${p.tiene_biblioteca?'':'disabled'}>${esc(p.id)}${p.tiene_biblioteca?'':' · Sin Biblioteca'}</button>`).join('')||'<p>No se encontraron cuentas de Drive.</p>';$('dialogBody').onclick=guard(async e=>{const id=e.target.closest('[data-profile]')?.dataset.profile;if(!id)return;await api('profile',{id});tagCatalog=null;S.selected=null;S.pinned=false;$('pin').setAttribute('aria-pressed','false');$('details').hidden=true;$('inspectorEmpty').hidden=false;$('dialog').close();S.tokens=[];setView('grid');await refresh();});});
$('viewport').addEventListener('keydown',guard(async e=>{
 if(S.view!=='grid'||e.altKey||e.ctrlKey||e.metaKey)return;
 const card=e.target.closest('.card');if(!card&&e.target!==$('viewport'))return;
 const selectedIndex=S.items.findIndex(item=>item.drive_id===S.selected?.drive_id),current=card?Number(card.dataset.index):Math.max(0,selectedIndex),width=$('viewport').clientWidth-56,cols=Math.max(1,Math.floor((width+20)/(S.zoom+20)));
 if(e.key==='Tab'&&!e.shiftKey&&card){e.preventDefault();await select(S.items[current].drive_id);$('hero').focus();return;}
 const next=({ArrowLeft:current-1,ArrowRight:current+1,ArrowUp:current-cols,ArrowDown:current+cols,Home:0,End:S.items.length-1})[e.key];
 if(next===undefined)return;e.preventDefault();if(next>=0&&next<S.items.length)await focusCardIndex(next);
}));
$('inspector').addEventListener('keydown',guard(async e=>{if(e.key==='Tab'&&e.shiftKey&&e.target===$('hero')){const index=S.items.findIndex(item=>item.drive_id===keyboardCardId);if(index>=0){e.preventDefault();await focusCardIndex(index,false);}}}));
$('viewport').addEventListener('scroll',scheduleDraw,{passive:true});new ResizeObserver(scheduleDraw).observe($('viewport'));
window.balisco={flush,windowState,close:guard(async()=>{await flush();await api('close');}),state:S};
async function boot(){if(ready)return;ready=true;try{windowState((await api('window_state'))?.maximized);const result=await api('bootstrap');S.mode=result.prefs.modo||'local';S.theme=result.prefs.tema||'auto';S.zoom=Number(result.prefs.zoom)||195;if(result.prefs.show_overlays!==undefined){S.showOverlays=result.prefs.show_overlays==='true';applyOverlayVisibility();}applyWallpaperOpacity(result.prefs.wallpaper_opacity??24);applyWallpaperBlur(result.prefs.wallpaper_blur??18);applyMode();applyTheme();if(result.prefs.wallpaper){await applyWallpaper(result.prefs.wallpaper);}await refresh();$('status').textContent='Biblioteca local · Lista';requestAnimationFrame(()=>requestAnimationFrame(()=>guard(()=>api('ready',{firstPaint:performance.now(),visibleCards:S.rows.size}))()));}catch(e){notify(e.message);$('summary').textContent='No se pudo conectar con la biblioteca';}}
window.addEventListener('pywebviewready',boot);if(window.pywebview?.api)boot();setTimeout(()=>{if(!ready){$('summary').textContent='Vista previa · inicia python main.py para conectar';$('status').textContent='Sin conexión al escritorio';}},1800);
