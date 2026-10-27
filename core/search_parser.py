"""Filtros acumulativos y parametrizados; texto sin operadores FTS inyectables."""
from copy import deepcopy
from pathlib import PureWindowsPath
import re
from uuid import uuid4
from .database import STATES, normalize_tag, normalize_search

import unicodedata

def strip_accents(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(s)) if not unicodedata.combining(c)).casefold()

BILINGUAL_MAP = {
    # Math & Exact Sciences
    'calculo': {'calculus'},
    'calculus': {'calculo'},
    'matematica': {'mathematics', 'math'},
    'matematicas': {'mathematics', 'math', 'maths'},
    'mathematics': {'matematica', 'matematicas'},
    'math': {'matematica', 'matematicas'},
    'maths': {'matematica', 'matematicas'},
    'algebra': {'algebra', 'algebraic'},
    'geometria': {'geometry', 'geometric'},
    'geometry': {'geometria'},
    'trigonometria': {'trigonometry'},
    'trigonometry': {'trigonometria'},
    'estadistica': {'statistics', 'statistical'},
    'statistics': {'estadistica'},
    'probabilidad': {'probability', 'probabilistic'},
    'probability': {'probabilidad'},
    'fisica': {'physics', 'physical'},
    'physics': {'fisica'},
    'quimica': {'chemistry', 'chemical'},
    'chemistry': {'quimica'},
    'biologia': {'biology', 'biological'},
    'biology': {'biologia'},
    'astronomia': {'astronomy'},
    'astronomy': {'astronomia'},

    # Technology & Engineering
    'computacion': {'computing', 'computer', 'computation'},
    'computer': {'computacion'},
    'computing': {'computacion'},
    'informatica': {'computing', 'informatics', 'computer'},
    'programacion': {'programming', 'coding', 'code'},
    'programming': {'programacion'},
    'codigo': {'code'},
    'code': {'codigo'},
    'desarrollo': {'development'},
    'development': {'desarrollo'},
    'algoritmo': {'algorithm'},
    'algoritmos': {'algorithms'},
    'algorithm': {'algoritmo'},
    'algorithms': {'algoritmos'},
    'estructura': {'structure'},
    'estructuras': {'structures'},
    'structure': {'estructura'},
    'structures': {'estructuras'},
    'redes': {'networks', 'networking'},
    'networks': {'redes'},
    'red': {'network'},
    'network': {'red'},
    'seguridad': {'security'},
    'security': {'seguridad'},
    'datos': {'data'},
    'data': {'datos'},
    'sistemas': {'systems', 'system'},
    'systems': {'sistemas'},
    'system': {'sistema'},
    'sistema': {'system'},
    'ingenieria': {'engineering', 'engineer'},
    'engineering': {'ingenieria'},
    'mecanica': {'mechanics', 'mechanical'},
    'mechanics': {'mecanica'},
    'electronica': {'electronics', 'electronic'},
    'electronics': {'electronica'},
    'electrica': {'electrical', 'electric'},
    'electricidad': {'electricity'},
    'robotica': {'robotics'},
    'robotics': {'robotica'},
    'inteligencia': {'intelligence'},
    'intelligence': {'inteligencia'},
    'artificial': {'artificial'},

    # Art, Animation, Design
    'diseno': {'design', 'designer'},
    'design': {'diseno'},
    'arte': {'art', 'artist'},
    'art': {'arte'},
    'artistico': {'artistic'},
    'artistic': {'artistico'},
    'dibujo': {'drawing', 'sketch'},
    'drawing': {'dibujo'},
    'pintura': {'painting', 'paint'},
    'painting': {'pintura'},
    'animacion': {'animation'},
    'animation': {'animacion'},
    'personaje': {'character'},
    'personajes': {'characters'},
    'character': {'personaje'},
    'characters': {'personajes'},
    'modelado': {'modeling', 'modelling'},
    'modeling': {'modelado'},
    'render': {'render', 'rendering'},
    'renderizado': {'rendering'},
    'rendering': {'render', 'renderizado'},
    'fotografia': {'photography', 'photo'},
    'photography': {'fotografia'},
    'musica': {'music', 'musical'},
    'music': {'musica'},
    'sonido': {'sound', 'audio'},
    'audio': {'audio', 'sound'},
    'sound': {'sonido'},
    'escultura': {'sculpture', 'sculpting'},
    'sculpture': {'escultura'},
    'anatomia': {'anatomy'},
    'anatomy': {'anatomia'},
    'color': {'color', 'colour'},

    # Humanities & Society
    'historia': {'history', 'historical'},
    'history': {'historia'},
    'filosofia': {'philosophy', 'philosophical'},
    'philosophy': {'filosofia'},
    'psicologia': {'psychology', 'psychological'},
    'psychology': {'psicologia'},
    'sociologia': {'sociology'},
    'sociology': {'sociologia'},
    'economia': {'economics', 'economy'},
    'economics': {'economia'},
    'finanzas': {'finance', 'financial'},
    'finance': {'finanzas'},
    'negocios': {'business'},
    'business': {'negocios'},
    'administracion': {'administration', 'management'},
    'management': {'administracion'},
    'contabilidad': {'accounting'},
    'accounting': {'contabilidad'},
    'marketing': {'marketing'},
    'derecho': {'law', 'legal'},
    'law': {'derecho'},
    'medicina': {'medicine', 'medical'},
    'medicine': {'medicina'},
    'literatura': {'literature'},
    'idioma': {'language'},
    'idiomas': {'languages'},
    'language': {'idioma'},
    'languages': {'idiomas'},
    'educacion': {'education', 'educational'},
    'education': {'educacion'},

    # Common Educational / Book terms
    'introduccion': {'introduction', 'intro'},
    'introduction': {'introduccion'},
    'intro': {'introduccion'},
    'avanzado': {'advanced'},
    'avanzada': {'advanced'},
    'advanced': {'avanzado', 'avanzada'},
    'basico': {'basic', 'basics'},
    'basica': {'basic'},
    'basic': {'basico', 'basica'},
    'basics': {'basico'},
    'fundamentos': {'fundamentals', 'fundamental'},
    'fundamentals': {'fundamentos'},
    'guia': {'guide', 'handbook'},
    'guide': {'guia'},
    'manual': {'manual'},
    'curso': {'course'},
    'cursos': {'courses'},
    'course': {'curso'},
    'courses': {'cursos'},
    'libro': {'book'},
    'libros': {'books'},
    'book': {'libro'},
    'books': {'libros'},
    'teoria': {'theory', 'theoretical'},
    'theory': {'teoria'},
    'practica': {'practice', 'practical'},
    'practico': {'practical'},
    'practice': {'practica'},
    'practical': {'practico', 'practica'},
    'ejercicios': {'exercises', 'exercise'},
    'exercise': {'ejercicio'},
    'exercises': {'ejercicios'},
    'problemas': {'problems', 'problem'},
    'problem': {'problema'},
    'problems': {'problemas'},
    'soluciones': {'solutions', 'solution'},
    'solution': {'solucion'},
    'solutions': {'soluciones'},
    'analisis': {'analysis'},
    'analysis': {'analisis'},
    'metodos': {'methods'},
    'metodo': {'method'},
    'method': {'metodo'},
    'methods': {'metodos'},
    'principios': {'principles', 'principle'},
    'principles': {'principios'},
    'conceptos': {'concepts'},
    'concepts': {'conceptos'},
    'completo': {'complete'},
    'completa': {'complete'},
    'complete': {'completo', 'completa'},
    'moderno': {'modern'},
    'moderna': {'modern'},
    'modern': {'moderno', 'moderna'},
    'clasico': {'classic', 'classical'},
    'clasica': {'classic', 'classical'},
    'classic': {'clasico', 'clasica'},
    'ciencia': {'science'},
    'ciencias': {'sciences'},
    'science': {'ciencia'},
    'sciences': {'ciencias'},
    'investigacion': {'research'},
    'research': {'investigacion'},
    'edicion': {'edition'},
    'edition': {'edicion'},
    'volumen': {'volume'},
    'volume': {'volumen'},
    'capitulo': {'chapter'},
    'chapter': {'capitulo'},
    'notas': {'notes'},
    'notes': {'notas'},
    'proyecto': {'project'},
    'proyectos': {'projects'},
    'project': {'proyecto'},
    'projects': {'proyectos'},
}

def morphological_variants(word):
    variants = set()
    if word.endswith('cion'):
        variants.add(word[:-4] + 'tion')
    elif word.endswith('tion'):
        variants.add(word[:-4] + 'cion')
    if word.endswith('ia') and len(word) > 3:
        variants.add(word[:-2] + 'y')
    elif word.endswith('y') and len(word) > 2:
        variants.add(word[:-1] + 'ia')
    if word.endswith('icas') or word.endswith('icos'):
        variants.add(word[:-4] + 'ics')
    elif word.endswith('ica') or word.endswith('ico'):
        variants.add(word[:-3] + 'ics')
    elif word.endswith('ics'):
        variants.add(word[:-3] + 'ica')
        variants.add(word[:-3] + 'ico')
    return variants

def expand_word(raw):
    norm = strip_accents(raw)
    if not norm:
        return set()
    variants = {norm}
    if norm in BILINGUAL_MAP:
        variants.update(BILINGUAL_MAP[norm])
    for syn in list(variants):
        variants.update(morphological_variants(syn))
    return {v for v in variants if v}

def fts_query(value):
    words = re.findall(r'[^\W_]+', str(value), re.UNICODE)
    if not words:
        return '""'
    word_clauses = []
    for raw in words:
        variants = expand_word(raw)
        if len(variants) == 1:
            word_clauses.append(f'"{list(variants)[0]}"*')
        else:
            or_parts = ' OR '.join(f'"{v}"*' for v in sorted(variants))
            word_clauses.append(f'({or_parts})')
    return ' AND '.join(word_clauses)

def limpiar_todos_filtros():
    return {"pildoras": []}

def parse_bytes(s):
    s = s.strip().lower()
    multipliers = {'g': 1024**3, 'gb': 1024**3, 'm': 1024**2, 'mb': 1024**2, 'k': 1024, 'kb': 1024, 'b': 1}
    m = re.match(r'^(\d+(?:\.\d+)?)\s*([a-z]+)?$', s)
    if not m:
        raise ValueError(f'Tamaño inválido: {s}')
    val = float(m.group(1))
    unit = m.group(2) or 'mb'
    if unit not in multipliers:
        raise ValueError(f'Unidad de tamaño desconocida: {unit}')
    return int(val * multipliers[unit])

def agregar_filtro(token, estado_actual_filtros):
    token = token.strip()
    if not token:
        return deepcopy(estado_actual_filtros)
    result = deepcopy(estado_actual_filtros)
    low = token.casefold()
    
    # 1. Tags OR: +tag1|tag2 o +tag1,tag2 / Exclusión: -tag1|tag2
    if token[0] in '+-' and ('|' in token or ',' in token):
        is_include = token[0] == '+'
        subtokens = [t.strip().casefold().lstrip('+-') for t in re.split(r'[,|]', token[1:]) if t.strip()]
        if not subtokens or any(any(c.isspace() for c in t) for t in subtokens):
            raise ValueError('Etiquetas vacías o con espacios')
        kind = 'tags_or' if is_include else 'tags_excluir_all'
        value = tuple(sorted(set(subtokens)))
        if not any(p['tipo'] == kind and p['valor'] == value for p in result['pildoras']):
            result['pildoras'].append(dict(id=uuid4().hex, tipo=kind, valor=value))
        return result

    # 2. Single tag: +tag o -tag
    if token[0] in '+-':
        kind = 'tags_incluir' if token[0] == '+' else 'tags_excluir'
        value = token[1:].strip().casefold()
        if not value or any(c.isspace() for c in value):
            raise ValueError('Etiqueta vacía o con espacios')
        if not any(p['tipo'] == kind and p['valor'] == value for p in result['pildoras']):
            result['pildoras'].append(dict(id=uuid4().hex, tipo=kind, valor=value))
        return result

    # 3. Autor
    if low.startswith('@autor:') or low.startswith('@autores:') or low.startswith('autor:'):
        prefix_len = 7 if low.startswith('@autor:') else (9 if low.startswith('@autores:') else 6)
        kind, value = 'autor', token[prefix_len:].strip().casefold()
        if not value: raise ValueError('Autor vacío')
        if not any(p['tipo'] == kind and p['valor'] == value for p in result['pildoras']):
            result['pildoras'].append(dict(id=uuid4().hex, tipo=kind, valor=value))
        return result

    # 4. Formato: @formato:epub, @formato:epub,pdf o @fmt:...
    if low.startswith('@formato:') or low.startswith('@fmt:'):
        spec = token[token.index(':')+1:].strip()
        formats = tuple(sorted(set(p.strip().upper() for p in spec.split(',') if p.strip())))
        if not formats: raise ValueError('Formato vacío')
        kind, value = 'formato', formats
        if not any(p['tipo'] == kind and p['valor'] == value for p in result['pildoras']):
            result['pildoras'].append(dict(id=uuid4().hex, tipo=kind, valor=value))
        return result

    # 5. Peso / Tamaño: @peso:... o @tamano:...
    if low.startswith('@peso:') or low.startswith('@tamano:'):
        spec = token[token.index(':')+1:].strip().lower()
        if not spec: raise ValueError('Especificación de peso vacía')
        m_cmp = re.match(r'^(>=|<=|>|<)\s*(.+)$', spec)
        if m_cmp:
            op, val_str = m_cmp.group(1), m_cmp.group(2)
            bytes_val = parse_bytes(val_str)
            kind, value = 'peso_cmp', (op, bytes_val)
        else:
            m_range = re.match(r'^(.+?)-(.+)$', spec)
            if m_range:
                min_b = parse_bytes(m_range.group(1))
                max_b = parse_bytes(m_range.group(2))
                if min_b > max_b: min_b, max_b = max_b, min_b
                kind, value = 'peso_range', (min_b, max_b)
            else:
                if spec.endswith('+'):
                    bytes_val = parse_bytes(spec[:-1])
                    kind, value = 'peso_cmp', ('>=', bytes_val)
                else:
                    bytes_val = parse_bytes(spec)
                    kind, value = 'peso_cmp', ('<=', bytes_val)
        if not any(p['tipo'] == kind and p['valor'] == value for p in result['pildoras']):
            result['pildoras'].append(dict(id=uuid4().hex, tipo=kind, valor=value))
        return result

    # 6. Rating: @rating:...
    if low.startswith('@rating:'):
        spec = token[8:].strip().casefold()
        if not spec: raise ValueError('Rating vacío')
        if spec in ('sin', 'none', '0'):
            kind, value = 'rating_exact', 0
        elif re.match(r'^[0-5]-[0-5]$', spec):
            r1, r2 = [int(x) for x in spec.split('-')]
            if r1 > r2: r1, r2 = r2, r1
            kind, value = 'rating_range', (r1, r2)
        elif spec.endswith('+') and spec[:-1].isdigit():
            r = int(spec[:-1])
            if r not in range(6): raise ValueError('Rating fuera de rango')
            kind, value = 'rating_gte', r
        elif re.match(r'^(>=|>|<=|<)([0-5])$', spec):
            m = re.match(r'^(>=|>|<=|<)([0-5])$', spec)
            op, r = m.group(1), int(m.group(2))
            kind, value = ('rating_gte' if op in ('>=', '>') else 'rating_lte'), (r if op != '>' else r + 1)
            if op == '<': value = r - 1
        elif ',' in spec:
            nums = tuple(sorted(set(int(x.strip()) for x in spec.split(',') if x.strip().isdigit() and int(x.strip()) in range(6))))
            if not nums: raise ValueError('Ratings inválidos')
            kind, value = 'rating_in', nums
        elif spec.isdigit():
            r = int(spec)
            if r not in range(6): raise ValueError('Rating fuera de rango')
            kind, value = 'rating_exact', r
        else:
            raise ValueError('Especificación de rating no reconocida')
        if not any(p['tipo'] == kind and p['valor'] == value for p in result['pildoras']):
            result['pildoras'].append(dict(id=uuid4().hex, tipo=kind, valor=value))
        return result

    # 7. Tipo: @tipo:documento, @tipo:documento,contenedor
    if low.startswith('@tipo:'):
        spec = token[6:].strip()
        raw_types = [t.strip().casefold() for t in spec.split(',') if t.strip()]
        for val in raw_types:
            if val == 'pdf': val = 'documento'
            elif val == 'archivo': val = 'otro'
            if val not in ('documento','contenedor','video','audio','imagen','otro'):
                raise ValueError(f'Tipo desconocido: {val}')
            if not any(p['tipo'] == 'tipo' and p['valor'] == val for p in result['pildoras']):
                result['pildoras'].append(dict(id=uuid4().hex, tipo='tipo', valor=val))
        return result

    # 8. Orden
    if low.startswith('@orden:'):
        ord_val = token[7:].casefold()
        if ord_val not in ('recientes','antiguos','abiertos','peso','ligero','alfabetico'):
            raise ValueError('Orden desconocido')
        result['pildoras'] = [p for p in result['pildoras'] if p['tipo'] != 'orden']
        result['pildoras'].append(dict(id=uuid4().hex, tipo='orden', valor=ord_val))
        return result

    # 9. Atajos rápidos / Mantenimiento
    if low in ('@ocultos', '@hidden'):
        if not any(p['tipo'] == 'ocultos' for p in result['pildoras']):
            result['pildoras'].append(dict(id=uuid4().hex, tipo='ocultos', valor=1))
        return result
    if low == '@recientes':
        if not any(p['tipo'] == 'historial' for p in result['pildoras']):
            result['pildoras'].append(dict(id=uuid4().hex, tipo='historial', valor=1))
        return result
    if low == '@favoritos':
        if not any(p['tipo'] == 'favoritos' for p in result['pildoras']):
            result['pildoras'].append(dict(id=uuid4().hex, tipo='favoritos', valor=1))
        return result
    if low == '@con:seguimiento':
        if not any(p['tipo'] == 'con_seguimiento' for p in result['pildoras']):
            result['pildoras'].append(dict(id=uuid4().hex, tipo='con_seguimiento', valor=1))
        return result

    # Mantenimiento
    if low in ('@sin:etiquetas', '@sin:tags'):
        if not any(p['tipo'] == 'sin_etiquetas' for p in result['pildoras']):
            result['pildoras'].append(dict(id=uuid4().hex, tipo='sin_etiquetas', valor=1))
        return result
    if low in ('@con:etiquetas', '@con:tags'):
        if not any(p['tipo'] == 'con_etiquetas' for p in result['pildoras']):
            result['pildoras'].append(dict(id=uuid4().hex, tipo='con_etiquetas', valor=1))
        return result
    if low in ('@con:notas', '@con:apuntes'):
        if not any(p['tipo'] == 'con_notas' for p in result['pildoras']):
            result['pildoras'].append(dict(id=uuid4().hex, tipo='con_notas', valor=1))
        return result
    if low in ('@sin:notas', '@sin:apuntes'):
        if not any(p['tipo'] == 'sin_notas' for p in result['pildoras']):
            result['pildoras'].append(dict(id=uuid4().hex, tipo='sin_notas', valor=1))
        return result
    if low == '@sin:autor':
        if not any(p['tipo'] == 'sin_autor' for p in result['pildoras']):
            result['pildoras'].append(dict(id=uuid4().hex, tipo='sin_autor', valor=1))
        return result
    if low in ('@sin:portada', '@sin:miniatura', '@sin:cover'):
        if not any(p['tipo'] == 'sin_portada' for p in result['pildoras']):
            result['pildoras'].append(dict(id=uuid4().hex, tipo='sin_portada', valor=1))
        return result
    if low in ('@con:portada', '@con:miniatura', '@con:cover'):
        if not any(p['tipo'] == 'con_portada' for p in result['pildoras']):
            result['pildoras'].append(dict(id=uuid4().hex, tipo='con_portada', valor=1))
        return result

    # 10. Exclusión de estados: @!leido o -@leido
    if token.startswith('@!') or token.startswith('-@'):
        state = token[2:].strip().casefold()
        if state not in STATES: raise ValueError(f'Estado desconocido: {state}')
        if not any(p['tipo'] == 'estado_excluir' and p['valor'] == state for p in result['pildoras']):
            result['pildoras'].append(dict(id=uuid4().hex, tipo='estado_excluir', valor=state))
        return result

    # 11. Estados: @estado:pendiente,leyendo o @pendiente
    if low.startswith('@estado:') or low.startswith('@estados:'):
        spec = token[token.index(':')+1:].strip().casefold()
        raw_states = [s.strip() for s in spec.split(',') if s.strip()]
        for s in raw_states:
            if s not in STATES: raise ValueError(f'Estado desconocido: {s}')
        kind, value = 'estados_in', tuple(sorted(set(raw_states)))
        if not any(p['tipo'] == kind and p['valor'] == value for p in result['pildoras']):
            result['pildoras'].append(dict(id=uuid4().hex, tipo=kind, valor=value))
        return result

    # Idioma: @idioma:español, @idioma:ingles o @lang:...
    if low.startswith('@idioma:') or low.startswith('@lang:'):
        spec = token[token.index(':')+1:].strip()
        if not spec: raise ValueError('Idioma vacío')
        kind, value = 'idioma', spec
        if not any(p['tipo'] == kind and p['valor'] == value for p in result['pildoras']):
            result['pildoras'].append(dict(id=uuid4().hex, tipo=kind, valor=value))
        return result

    if token.startswith('@'):
        spec = token[1:].casefold()
        if ',' in spec:
            raw_states = [s.strip() for s in spec.split(',') if s.strip()]
            for s in raw_states:
                if s not in STATES: raise ValueError(f'Estado desconocido: {s}')
            kind, value = 'estados_in', tuple(sorted(set(raw_states)))
            if not any(p['tipo'] == kind and p['valor'] == value for p in result['pildoras']):
                result['pildoras'].append(dict(id=uuid4().hex, tipo=kind, valor=value))
            return result
        if spec in STATES:
            if not any(p['tipo'] == 'estados' and p['valor'] == spec for p in result['pildoras']):
                result['pildoras'].append(dict(id=uuid4().hex, tipo='estados', valor=spec))
            return result
        raise ValueError('Estado desconocido')

    # Texto libre
    if not any(p['tipo'] == 'texto_titulo' and p['valor'] == token for p in result['pildoras']):
        result['pildoras'].append(dict(id=uuid4().hex, tipo='texto_titulo', valor=token))
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
            params.append('{titulo autor etiquetas notas} : ('+query+')')
        elif kind in ('tags_incluir','tags_excluir'):
            clauses.append("instr(' ' || normalize_tag(i.etiquetas) || ' ', ?) "+('> 0' if kind=='tags_incluir' else '= 0'))
            params.append(' +' + normalize_tag(value) + ' ')
        elif kind == 'tags_or':
            tag_clauses = ["instr(' ' || normalize_tag(i.etiquetas) || ' ', ?) > 0" for _ in value]
            clauses.append('(' + ' OR '.join(tag_clauses) + ')')
            params.extend([' +' + normalize_tag(t) + ' ' for t in value])
        elif kind == 'tags_excluir_all':
            tag_clauses = ["instr(' ' || normalize_tag(i.etiquetas) || ' ', ?) = 0" for _ in value]
            clauses.append('(' + ' AND '.join(tag_clauses) + ')')
            params.extend([' +' + normalize_tag(t) + ' ' for t in value])
        elif kind == 'idioma':
            clauses.append("normalize_search(i.idioma) = normalize_search(?)")
            params.append(value)
        elif kind=='autor':
            clauses.append("instr(char(10) || unicode_casefold(i.autor) || char(10), char(10) || ? || char(10)) > 0")
            params.append(value)
        elif kind in ('rating', 'rating_exact'):
            clauses.append('i.rating = ?')
            params.append(value)
        elif kind == 'rating_range':
            clauses.append('i.rating BETWEEN ? AND ?')
            params.extend([value[0], value[1]])
        elif kind == 'rating_gte':
            clauses.append('i.rating >= ?')
            params.append(value)
        elif kind == 'rating_lte':
            clauses.append('i.rating <= ?')
            params.append(value)
        elif kind == 'rating_in':
            marks = ','.join('?' for _ in value)
            clauses.append(f'i.rating IN ({marks})')
            params.extend(value)
        elif kind == 'formato':
            marks = ','.join('?' for _ in value)
            clauses.append(f'UPPER(i.formato) IN ({marks})')
            params.extend(value)
        elif kind == 'peso_range':
            clauses.append('i.tamano_bytes BETWEEN ? AND ?')
            params.extend([value[0], value[1]])
        elif kind == 'peso_cmp':
            op, b_val = value
            clauses.append(f'i.tamano_bytes {op} ?')
            params.append(b_val)
        elif kind in ('estados',):
            clauses.append('i.estado_lectura = ?')
            params.append(value)
        elif kind == 'estados_in':
            marks = ','.join('?' for _ in value)
            clauses.append(f'i.estado_lectura IN ({marks})')
            params.extend(value)
        elif kind == 'estado_excluir':
            clauses.append('i.estado_lectura != ?')
            params.append(value)
        elif kind == 'favoritos':
            clauses.append('i.es_favorito = ?')
            params.append(value)
        elif kind == 'con_seguimiento':
            clauses.append("(i.es_favorito=1 OR COALESCE(i.rating,0)>0 OR (i.estado_lectura IS NOT NULL AND i.estado_lectura NOT IN ('','pendiente')) OR trim(COALESCE(i.notas,''))!='')")
        elif kind == 'sin_etiquetas':
            clauses.append("(i.etiquetas IS NULL OR trim(i.etiquetas) = '')")
        elif kind == 'con_etiquetas':
            clauses.append("(i.etiquetas IS NOT NULL AND trim(i.etiquetas) != '')")
        elif kind == 'con_notas':
            clauses.append("(i.notas IS NOT NULL AND trim(i.notas) != '')")
        elif kind == 'sin_notas':
            clauses.append("(i.notas IS NULL OR trim(i.notas) = '')")
        elif kind == 'sin_autor':
            clauses.append("(i.autor IS NULL OR trim(i.autor) = '')")
        elif kind in ('sin_portada', 'con_portada'):
            continue
        else: raise ValueError('Filtro desconocido')
    sort=next((p['valor'] for p in reversed(filtros_activos['pildoras']) if p['tipo']=='orden'),'recientes')
    order={
        'recientes':"i.fijado DESC, (i.ultimo_acceso IS NOT NULL AND i.recent_hidden=0) DESC, CASE WHEN i.recent_hidden=0 THEN MAX(COALESCE(i.ultimo_acceso,''),COALESCE(i.fecha_agregado,'')) ELSE i.fecha_agregado END DESC, i.id DESC",
        'antiguos':'i.fijado DESC, i.fecha_agregado ASC, i.id ASC',
        'abiertos':'i.fijado DESC, (i.ultimo_acceso IS NULL OR i.recent_hidden=1), CASE WHEN i.recent_hidden=0 THEN i.ultimo_acceso END DESC, i.id DESC',
        'peso':'i.fijado DESC, i.tamano_bytes DESC, i.id DESC',
        'ligero':'i.fijado DESC, i.tamano_bytes ASC, i.id ASC',
        'alfabetico':'i.fijado DESC, i.titulo COLLATE NOCASE ASC, i.id ASC',
    }[sort]
    return 'SELECT i.* FROM items i WHERE '+' AND '.join(clauses)+' ORDER BY '+order,params

def buscar(db, filtros, perfil=None, limite=200, offset=0):
    sql,params=construir_query_sql(filtros,perfil)
    limit=max(1,min(int(limite),1000));start=max(0,int(offset))
    if not any(p['tipo']=='texto_titulo' for p in filtros['pildoras']):
        return [dict(row) for row in db.execute(sql+' LIMIT ? OFFSET ?',params+[limit,start])]
    cache={};rows=[]
    for row in db.execute(sql,params):
        item=dict(row)
        if internal_searchable(db,item,cache):
            rows.append(item)
            if len(rows)>=start+limit:break
    return rows[start:]

def internal_searchable(db,item,cache=None):
    if not item['container_parent'] or item['fijado']:return True
    cache={} if cache is None else cache
    root=item['container_parent']
    if root not in cache:
        parent=db.execute('SELECT indexar_contenido FROM items WHERE drive_id=?',(root,)).fetchone()
        overrides={tuple(part.casefold() for part in PureWindowsPath(row['ruta_relativa']).parts):row['search_override']
                   for row in db.execute("SELECT ruta_relativa,search_override FROM items WHERE container_parent=? AND tipo='curso' AND disponible=1",(root,))
                   if row['search_override']!=-1}
        cache[root]=(parent,overrides)
    parent,overrides=cache[root]
    if not parent:return False
    enabled=bool(parent['indexar_contenido']);path=tuple(part.casefold() for part in PureWindowsPath(item['ruta_relativa']).parts)
    for depth in range(1,len(path)):
        override=overrides.get(path[:depth])
        if override is not None:enabled=bool(override)
    if item['search_override']!=-1:enabled=bool(item['search_override'])
    return enabled

def buscar_global(db, texto):
    filters=agregar_filtro(texto,limpiar_todos_filtros())
    return buscar(db,filters,limite=200)
