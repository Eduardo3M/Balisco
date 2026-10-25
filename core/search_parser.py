"""Filtros acumulativos y parametrizados; texto sin operadores FTS inyectables."""
from copy import deepcopy
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
        if kind=='texto_titulo':
            query=fts_query(value)
            clauses.append('''(i.id IN (SELECT rowid FROM items_fts WHERE items_fts MATCH ?)
                OR (i.tipo='curso' AND i.indexar_contenido=1 AND i.drive_id IN
                    (SELECT e.container_drive_id FROM container_entries e JOIN container_entries_fts f ON f.rowid=e.id
                     WHERE container_entries_fts MATCH ?)))''')
            params.extend(('{titulo autor notas} : ('+query+')',query))
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
        'recientes':"MAX(COALESCE(i.ultimo_acceso,''),COALESCE(i.fecha_agregado,'')) DESC, i.id DESC",
        'antiguos':'i.fecha_agregado ASC, i.id ASC',
        'abiertos':'i.ultimo_acceso IS NULL, i.ultimo_acceso DESC, i.id DESC',
        'peso':'i.tamano_bytes DESC, i.id DESC',
        'ligero':'i.tamano_bytes ASC, i.id ASC',
        'alfabetico':'i.titulo COLLATE NOCASE ASC, i.id ASC',
    }[sort]
    return 'SELECT i.* FROM items i WHERE '+' AND '.join(clauses)+' ORDER BY '+order,params

def buscar(db, filtros, perfil=None, limite=200, offset=0):
    sql,params=construir_query_sql(filtros,perfil)
    return [dict(r) for r in db.execute(sql+' LIMIT ? OFFSET ?',params+[max(1,min(int(limite),1000)),max(0,int(offset))])]

def buscar_global(db, texto):
    filters=agregar_filtro(texto,limpiar_todos_filtros())
    return buscar(db,filters,limite=200)
