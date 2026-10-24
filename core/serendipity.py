import random
from collections import Counter
from .tags_manager import normalizar

def obtener_aleatorio_puro(conexion_db, perfil=None):
    row=conexion_db.execute('SELECT * FROM items WHERE disponible=1'+(' AND perfil_drive=?' if perfil is not None else '')+' ORDER BY RANDOM() LIMIT 1',([] if perfil is None else [perfil])).fetchone()
    return dict(row) if row else None

def obtener_semi_aleatorio_contextual(conexion_db, limite_historial=8, perfil=None):
    scope='disponible=1'+(' AND perfil_drive=?' if perfil is not None else '')
    args=[] if perfil is None else [perfil]
    recent=conexion_db.execute('SELECT etiquetas FROM items WHERE '+scope+' AND ultimo_acceso IS NOT NULL ORDER BY ultimo_acceso DESC LIMIT ?',args+[max(1,int(limite_historial))]).fetchall()
    interests=Counter()
    for index,row in enumerate(recent):
        for tag in normalizar(row[0]): interests[tag]+=1/(index+1)
    candidates=[]; weights=[]
    for row in conexion_db.execute("SELECT * FROM items WHERE "+scope+" AND estado_lectura!='leido'",args):
        weight=sum(interests[t] for t in normalizar(row['etiquetas']))
        if weight: candidates.append(dict(row)); weights.append(weight)
    return random.choices(candidates,weights=weights,k=1)[0] if candidates else obtener_aleatorio_puro(conexion_db,perfil)
