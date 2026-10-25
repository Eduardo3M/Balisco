import random
import math
import re
import unicodedata
from collections import Counter
from .tags_manager import normalizar

_STOPWORDS=set('a al algo algunas algunos ante antes como con contra cual cuando de del desde donde durante e el ella ellas ellos en entre era es esa esas ese eso esos esta estaba estas este esto estos fue ha hacia hasta hay la las le les lo los mas me mi mis mucho muy ni no nos o os otra otras otro otros para pero por porque que quien se sin sobre su sus te tu tus un una unas uno unos y ya the a an and are as at be by for from has in into is it its of on or that the their then there these they this to was were with'.split())

def _words(value):
    normalized=unicodedata.normalize('NFKD',str(value or '').casefold())
    normalized=''.join(char for char in normalized if not unicodedata.combining(char))
    return [word for word in re.findall(r'[a-z0-9]{2,}',normalized) if word not in _STOPWORDS]

def _text_vector(row):
    fields=(('titulo',3.0),('etiquetas',2.8),('autor',2.2),('categoria_macro',1.2),('subcategoria',1.2),('notas',.45))
    vector={}
    for field,weight in fields:
        value=row[field] if field in row.keys() else ''
        for word in _words(value): vector[word]=vector.get(word,0)+weight
    return vector

def _char_vector(row):
    # Character trigrams let close forms such as "sex" / "sexual" match,
    # while field weighting keeps title and tags more influential than notes.
    fields=(('titulo',3.0),('etiquetas',2.8),('autor',2.2),('categoria_macro',1.2),('subcategoria',1.2),('notas',.25))
    vector={}
    for field,weight in fields:
        value=row[field] if field in row.keys() else ''
        text=' '.join(_words(value))
        for word in text.split():
            padded='^'+word+'$'
            grams={padded[i:i+3] for i in range(max(1,len(padded)-2))}
            for gram in grams:vector[gram]=vector.get(gram,0)+weight
    return vector

def _text_similarity(left,right,idf):
    if not left or not right:return 0.0
    a={word:value*idf.get(word,1) for word,value in left.items()}
    b={word:value*idf.get(word,1) for word,value in right.items()}
    common=a.keys()&b.keys()
    if not common:return 0.0
    dot=sum(a[word]*b[word] for word in common)
    norm_a=math.sqrt(sum(value*value for value in a.values()))
    norm_b=math.sqrt(sum(value*value for value in b.values()))
    return dot/(norm_a*norm_b) if norm_a and norm_b else 0.0

def obtener_aleatorio_puro(conexion_db, perfil=None):
    row=conexion_db.execute('SELECT * FROM items WHERE disponible=1 AND oculto=0'+(' AND perfil_drive=?' if perfil is not None else '')+' ORDER BY RANDOM() LIMIT 1',([] if perfil is None else [perfil])).fetchone()
    return dict(row) if row else None

def obtener_semi_aleatorio_contextual(conexion_db, limite_historial=8, perfil=None):
    scope='disponible=1 AND oculto=0'+(' AND perfil_drive=?' if perfil is not None else '')
    args=[] if perfil is None else [perfil]
    rows=[dict(r) for r in conexion_db.execute('SELECT * FROM items WHERE '+scope,args)]
    if len(rows)<2:return obtener_aleatorio_puro(conexion_db,perfil)
    by_id={row['drive_id']:row for row in rows}
    history=sorted((r for r in rows if r['ultimo_acceso']),key=lambda r:r['ultimo_acceso'],reverse=True)[:max(8,min(30,int(limite_historial)*3))]
    if not history:return obtener_aleatorio_puro(conexion_db,perfil)
    history_ids={row['drive_id'] for row in history}
    n=len(rows)
    tag_df=Counter(tag for row in rows for tag in set(normalizar(row['etiquetas'])))
    author_df=Counter(author.casefold().strip() for row in rows for author in str(row['autor'] or '').splitlines() if author.strip())
    word_df=Counter(word for row in rows for word in set(_words(row['titulo']+' '+row['notas'])))
    idf=lambda df:math.log(1+(n+1)/(df+1))+1
    tag_profile=Counter();author_profile=Counter();word_profile=Counter()
    positive=[];negative=[]
    for index,row in enumerate(history):
        recency=.88**index
        engagement=1.0
        if row['es_favorito']:engagement*=1.35
        if row['rating']>=4:engagement*=1+(.12*row['rating'])
        elif row['rating'] in (1,2):engagement*=.35
        for tag in set(normalizar(row['etiquetas'])):tag_profile[tag]+=recency*engagement*idf(tag_df[tag])
        for author in {a.casefold().strip() for a in str(row['autor'] or '').splitlines() if a.strip()}:
            author_profile[author]+=recency*engagement*idf(author_df[author])
        for word in set(_words(row['titulo']+' '+row['notas'])):word_profile[word]+=recency*engagement*idf(word_df[word])
        if row['es_favorito'] or row['rating']>=4:positive.append(row)
        if row['rating'] in (1,2):negative.append(row)
    def affinity(candidate,seed):
        ctags=set(normalizar(candidate['etiquetas']));stags=set(normalizar(seed['etiquetas']))
        tag_score=sum(idf(tag_df[t]) for t in ctags&stags)/max(1,sum(idf(tag_df[t]) for t in stags))
        cauth={a.casefold().strip() for a in str(candidate['autor'] or '').splitlines() if a.strip()}
        sauth={a.casefold().strip() for a in str(seed['autor'] or '').splitlines() if a.strip()}
        author_score=1.0 if cauth&sauth else 0.0
        title_score=.72*_text_similarity({w:1 for w in _words(candidate['titulo'])},{w:1 for w in _words(seed['titulo'])},{w:idf(word_df[w]) for w in set(_words(candidate['titulo']+' '+seed['titulo']))})+.28*_text_similarity(_char_vector(candidate),_char_vector(seed),{})
        return .45*tag_score+.30*author_score+.25*title_score
    candidates=[];weights=[]
    for row in rows:
        if row['estado_lectura']=='leido' or row['drive_id'] in history_ids:continue
        tag_score=sum(tag_profile[t] for t in set(normalizar(row['etiquetas'])))
        authors={a.casefold().strip() for a in str(row['autor'] or '').splitlines() if a.strip()}
        author_score=sum(author_profile[a] for a in authors)
        words=set(_words(row['titulo']+' '+row['notas']))
        word_score=sum(word_profile[w] for w in words)
        personalization=.5*tag_score+.25*author_score+.25*word_score
        feedback=sum(affinity(row,seed)*(.7 if seed['rating']>=4 else .5) for seed in positive[:12])
        dislikes=sum(affinity(row,seed)*(.4 if seed['rating']==1 else .25) for seed in negative[:8])
        score=personalization+feedback-dislikes
        if row['es_favorito']:score*=.15 # do not keep recommending items already marked as favorites
        if row['rating'] in (1,2):score*=.22
        # Softmax-style temperature leaves some exploration while favoring strong matches.
        weight=math.exp(min(20,max(-20,score/max(1.0,math.sqrt(len(tag_profile)+len(author_profile)+len(word_profile))))))
        if score>0:weight*=1.15
        candidates.append(row);weights.append(weight)
    return random.choices(candidates,weights=weights,k=1)[0] if candidates else obtener_aleatorio_puro(conexion_db,perfil)

def obtener_similares(conexion_db, identificador, perfil, limite=80):
    source=conexion_db.execute('SELECT * FROM items WHERE drive_id=? AND perfil_drive=? AND disponible=1',(identificador,perfil)).fetchone()
    if source is None: raise ValueError('Selecciona un elemento visible')
    rows=list(conexion_db.execute('SELECT * FROM items WHERE perfil_drive=? AND disponible=1 AND oculto=0',(perfil,)))
    fields=('titulo','etiquetas','autor','notas')
    field_vectors={field:{row['drive_id']:{word:1 for word in _words(row[field])} for row in rows} for field in fields}
    def char_terms(value):
        result=set()
        for word in _words(value):
            padded='^'+word+'$'
            result.update(padded[i:i+3] for i in range(max(1,len(padded)-2)))
        return result
    field_chars={field:{row['drive_id']:{gram:1 for gram in char_terms(row[field])} for row in rows} for field in fields}
    idfs={}
    count=max(1,len(rows))
    for field in fields:
        df={}
        for vector in field_vectors[field].values():
            for word in vector:df[word]=df.get(word,0)+1
        idfs[field]={word:math.log(1+(count+1)/(frequency+1))+1 for word,frequency in df.items()}
    def field_score(field,left,right):
        return .72*_text_similarity(field_vectors[field][left],field_vectors[field][right],idfs[field])+.28*_text_similarity(field_chars[field][left],field_chars[field][right],idfs[field])
    candidates=[]
    for row in rows:
        if row['drive_id']==identificador:continue
        ident=row['drive_id']
        title_score=field_score('titulo',identificador,ident)
        tags_score=field_score('etiquetas',identificador,ident)
        author_score=field_score('autor',identificador,ident)
        notes_score=field_score('notas',identificador,ident)
        # Broad shared labels should never outrank a meaningful title match.
        lexical_score=.72*title_score+.16*tags_score+.09*author_score+.03*notes_score
        size_score=0.0
        if source['tamano_bytes'] and row['tamano_bytes'] and row['tipo']==source['tipo']:
            ratio=abs(row['tamano_bytes']-source['tamano_bytes'])/max(row['tamano_bytes'],source['tamano_bytes'])
            if ratio<=.75:size_score=1-ratio
        # Text relevance leads; close file size breaks ties and supplies weak matches.
        score=lexical_score+.035*size_score
        if lexical_score>0 or size_score>0:candidates.append((row['drive_id'],score,lexical_score,size_score))
    candidates.sort(key=lambda entry:(-entry[1],-entry[2],-entry[3],entry[0]))
    ids=[identificador]+[entry[0] for entry in candidates[:max(0,limite-1)]]
    has_text=any(entry[2]>0 for entry in candidates)
    has_size=any(entry[3]>0 and entry[2]==0 for entry in candidates)
    basis='palabras y tamaño' if has_text and has_size else 'palabras' if has_text else 'tamaño' if has_size else 'ninguna'
    return {'ids':ids,'basis':basis}
