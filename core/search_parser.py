"""Filtros acumulativos y parametrizados; texto sin operadores FTS inyectables."""
from copy import deepcopy
from pathlib import PureWindowsPath
import re
from uuid import uuid4
from .database import STATES

def fts_query(value):
    words=re.findall(r'\w+',str(value),re.UNICODE)
    return ' AND '.join('"'+word+'"*' for word in words) if words else '""'

def limpiar_todos_filtros():
    return {"pildoras": []}

def agregar_filtro(token, estado_actual_filtros):
    token=token.strip()
    if not token:
        return deepcopy(estado_actual_filtros)
    kind, value = 'texto_titulo', token
    if token[0] in '+-':
        kind='tags_incluir' if token[0]=='+' else 'tags_excluir'
        value=token[1:].strip().casefold()
        if not value or any(c.isspace() for c in value):
            raise ValueError('Etiqueta vacía o con espacios')
    elif token.casefold().startswith('autor:'):
        kind,value='autor',token[6:].strip().casefold()
        if not value: raise ValueError('Autor vacío')
    elif token.startswith('@rating:'):
        kind,value='rating',int(token[8:])
        if value not in range(6): raise ValueError('Rating fuera de rango')
    elif token.startswith('@tipo:'):
        kind,value='tipo',token[6:]
        if value=='pdf': value='documento'  # Filtros guardados por versiones anteriores.
        if value not in ('documento','contenedor','video','audio','imagen','otro','archivo'): raise ValueError('Tipo desconocido')
        if value=='archivo': value='otro'
    elif token.casefold().startswith('@orden:'):
        kind,value='orden',token[7:].casefold()
        if value not in ('recientes','antiguos','abiertos','peso','ligero','alfabetico'):
            raise ValueError('Orden desconocido')
    elif token.casefold() in ('@ocultos','@hidden'):
        kind,value='ocultos',1
    elif token.casefold()=='@recientes':
        kind,value='historial',1
    elif token=='@favoritos':
        kind,value='favoritos',1
    elif token.startswith('@'):
        kind,value='estados',token[1:].casefold()
        if value not in STATES: raise ValueError('Estado desconocido')
    result=deepcopy(estado_actual_filtros)
    if kind=='orden':
        result['pildoras']=[p for p in result['pildoras'] if p['tipo']!='orden']
    if not any(p['tipo']==kind and p['valor']==value for p in result['pildoras']):
        result['pildoras'].append(dict(id=uuid4().hex,tipo=kind,valor=value))
    return result

def remover_filtro(id_pildora, estado_actual_filtros):
    result=deepcopy(estado_actual_filtros)
    result['pildoras']=[p for p in result['pildoras'] if p['id']!=id_pildora]
    return result

def construir_query_sql(filtros_activos, perfil=None):
    hidden=any(p['tipo']=='ocultos' for p in filtros_activos['pildoras'])
    clauses=['i.disponible=1','i.oculto='+('1' if hidden else '0')]; params=[]
    if perfil is not None:
        clauses.append('i.perfil_drive=?'); params.append(perfil)
    has_text=any(p['tipo']=='texto_titulo' for p in filtros_activos['pildoras'])
    history=any(p['tipo']=='historial' for p in filtros_activos['pildoras'])
    clauses.append("(i.container_parent='' OR i.fijado=1"+(" OR i.container_parent!=''" if has_text or history else '')+")")
    tipos=[p['valor'] for p in filtros_activos['pildoras'] if p['tipo']=='tipo']
    if tipos:
        choices=[]
        archive_in_containers="(i.tipo='archivo' AND i.categoria_macro='Containers' AND COALESCE(i.subcategoria,'')='' AND (lower(i.ruta_relativa) GLOB '*.zip' OR lower(i.ruta_relativa) GLOB '*.rar'))"
        for kind in tipos:
            if kind=='contenedor':choices.append("(i.tipo='curso' OR "+archive_in_containers+")")
            elif kind=='archivo':choices.append("(i.tipo='archivo' AND NOT "+archive_in_containers+")")
            elif kind=='documento':choices.append("(i.tipo_contenido='documento' OR (i.tipo_contenido='' AND i.tipo='pdf'))")
            elif kind=='otro':choices.append("(i.tipo='archivo' AND NOT "+archive_in_containers+")")
            else:choices.append('i.tipo=?');params.append(kind)
        clauses.append('('+' OR '.join(choices)+')')
    for p in filtros_activos['pildoras']:
        kind,value=p['tipo'],p['valor']
        if kind in ('tipo','orden','ocultos'):
            continue
        if kind=='historial':
            clauses.append('i.ultimo_acceso IS NOT NULL AND i.recent_hidden=0')
            continue
        if kind=='texto_titulo':
            query=fts_query(value)
            clauses.append('i.id IN (SELECT rowid FROM items_fts WHERE items_fts MATCH ?)')
            params.append('{titulo autor notas} : ('+query+')')
        elif kind in ('tags_incluir','tags_excluir'):
            clauses.append("instr(' ' || i.etiquetas || ' ', ?) "+('> 0' if kind=='tags_incluir' else '= 0'))
            params.append(' +'+value+' ')
        elif kind=='autor':
            clauses.append("instr(char(10) || unicode_casefold(i.autor) || char(10), char(10) || ? || char(10)) > 0")
            params.append(value)
        elif kind in ('rating','tipo','estados','favoritos'):
            column={'rating':'rating','tipo':'tipo','estados':'estado_lectura','favoritos':'es_favorito'}[kind]
            clauses.append('i.'+column+'=?'); params.append(value)
        else: raise ValueError('Filtro desconocido')
    sort=next((p['valor'] for p in reversed(filtros_activos['pildoras']) if p['tipo']=='orden'),'recientes')
    order={
        'recientes':"i.fijado DESC, MAX(COALESCE(i.ultimo_acceso,''),COALESCE(i.fecha_agregado,'')) DESC, i.id DESC",
        'antiguos':'i.fijado DESC, i.fecha_agregado ASC, i.id ASC',
        'abiertos':'i.fijado DESC, i.ultimo_acceso IS NULL, i.ultimo_acceso DESC, i.id DESC',
        'peso':'i.fijado DESC, i.tamano_bytes DESC, i.id DESC',
        'ligero':'i.fijado DESC, i.tamano_bytes ASC, i.id ASC',
        'alfabetico':'i.fijado DESC, i.titulo COLLATE NOCASE ASC, i.id ASC',
    }[sort]
    return 'SELECT i.* FROM items i WHERE '+' AND '.join(clauses)+' ORDER BY '+order,params

def buscar(db, filtros, perfil=None, limite=200, offset=0):
    sql,params=construir_query_sql(filtros,perfil)
    rows=[dict(r) for r in db.execute(sql,params)]
    if any(p['tipo']=='texto_titulo' for p in filtros['pildoras']):
        cache={}
        rows=[row for row in rows if internal_searchable(db,row,cache)]
    return rows[max(0,int(offset)):max(0,int(offset))+max(1,min(int(limite),1000))]

def internal_searchable(db,item,cache=None):
    if not item['container_parent'] or item['fijado']:return True
    cache={} if cache is None else cache
    root=item['container_parent']
    if root not in cache:
        parent=db.execute('SELECT indexar_contenido FROM items WHERE drive_id=?',(root,)).fetchone()
        folders=[dict(row) for row in db.execute("SELECT ruta_relativa,search_override FROM items WHERE container_parent=? AND tipo='curso' AND disponible=1",(root,))]
        cache[root]=(parent,folders)
    parent,folders=cache[root]
    if not parent:return False
    enabled=bool(parent['indexar_contenido']);path=tuple(part.casefold() for part in PureWindowsPath(item['ruta_relativa']).parts)
    for folder in sorted(folders,key=lambda f:len(PureWindowsPath(f['ruta_relativa']).parts)):
        parts=tuple(part.casefold() for part in PureWindowsPath(folder['ruta_relativa']).parts)
        if len(parts)<len(path) and path[:len(parts)]==parts and folder['search_override']!=-1:
            enabled=bool(folder['search_override'])
    if item['search_override']!=-1:enabled=bool(item['search_override'])
    return enabled

def buscar_global(db, texto):
    filters=agregar_filtro(texto,limpiar_todos_filtros())
    return buscar(db,filters,limite=200)
