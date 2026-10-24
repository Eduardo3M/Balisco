"""Filtros acumulativos y parametrizados; texto sin operadores FTS inyectables."""
from copy import deepcopy
import re
from uuid import uuid4
from .database import STATES

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
        if value not in ('pdf','curso','video'): raise ValueError('Tipo desconocido')
    elif token=='@favoritos':
        kind,value='favoritos',1
    elif token.startswith('@'):
        kind,value='estados',token[1:].casefold()
        if value not in STATES: raise ValueError('Estado desconocido')
    result=deepcopy(estado_actual_filtros)
    if not any(p['tipo']==kind and p['valor']==value for p in result['pildoras']):
        result['pildoras'].append(dict(id=uuid4().hex,tipo=kind,valor=value))
    return result

def remover_filtro(id_pildora, estado_actual_filtros):
    result=deepcopy(estado_actual_filtros)
    result['pildoras']=[p for p in result['pildoras'] if p['id']!=id_pildora]
    return result

def construir_query_sql(filtros_activos, perfil=None):
    clauses=['i.disponible=1']; params=[]
    if perfil is not None:
        clauses.append('i.perfil_drive=?'); params.append(perfil)
    tipos=[p['valor'] for p in filtros_activos['pildoras'] if p['tipo']=='tipo']
    if tipos:
        clauses.append('i.tipo IN ('+','.join('?' for _ in tipos)+')')
        params.extend(tipos)
    for p in filtros_activos['pildoras']:
        kind,value=p['tipo'],p['valor']
        if kind=='tipo':
            continue
        if kind=='estados' and value=='pendiente':
            continue
        if kind=='texto_titulo':
            clauses.append('i.id IN (SELECT rowid FROM items_fts WHERE items_fts MATCH ?)')
            words=re.findall(r'\w+',str(value),re.UNICODE)
            params.append('{titulo autor notas} : ('+' AND '.join('"'+word+'"*' for word in words)+')' if words else '""')
        elif kind in ('tags_incluir','tags_excluir'):
            clauses.append("instr(' ' || i.etiquetas || ' ', ?) "+('> 0' if kind=='tags_incluir' else '= 0'))
            params.append(' +'+value+' ')
        elif kind=='autor':
            clauses.append("instr(char(10) || unicode_casefold(i.autor) || char(10), char(10) || ? || char(10)) > 0")
            params.append(value)
        elif kind in ('rating','tipo','estados','favoritos'):
            column={'rating':'rating','tipo':'tipo','estados':'estado_lectura','favoritos':'es_favorito'}[kind]
            clauses.append('i.'+column+('>=?' if kind=='rating' else '=?')); params.append(value)
        else: raise ValueError('Filtro desconocido')
    return 'SELECT i.* FROM items i WHERE '+' AND '.join(clauses)+' ORDER BY i.titulo COLLATE NOCASE, i.id',params

def buscar(db, filtros, perfil=None, limite=200, offset=0):
    sql,params=construir_query_sql(filtros,perfil)
    return [dict(r) for r in db.execute(sql+' LIMIT ? OFFSET ?',params+[max(1,min(int(limite),1000)),max(0,int(offset))])]

def buscar_global(db, texto):
    query='"'+texto.replace('"','""')+'"'
    return [dict(r) for r in db.execute('SELECT i.* FROM items i JOIN items_fts f ON f.rowid=i.id WHERE items_fts MATCH ? AND i.disponible=1 LIMIT 200',(query,))]
