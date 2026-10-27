from collections import Counter

def normalizar(texto):
    return list(dict.fromkeys(t.lstrip('+').casefold() for t in str(texto or '').split() if t.lstrip('+')))

def obtener_etiquetas_ordenadas_frecuencia(conexion_db, perfil=None):
    sql="SELECT etiquetas FROM items WHERE disponible=1 AND oculto=0 AND etiquetas != '' AND etiquetas IS NOT NULL"
    params=[]
    if perfil is not None: sql+=' AND perfil_drive=?'; params=[perfil]
    counts=Counter(t for row in conexion_db.execute(sql,params) for t in normalizar(row[0]))
    return [dict(tag=t,total=n) for t,n in sorted(counts.items(),key=lambda x:(-x[1],x[0]))]

def obtener_sugerencias_etiquetas(conexion_db, perfil=None):
    sql="SELECT etiquetas,ultimo_acceso,recent_hidden,fecha_agregado FROM items WHERE disponible=1 AND oculto=0 AND etiquetas != '' AND etiquetas IS NOT NULL"
    params=[]
    if perfil is not None: sql+=' AND perfil_drive=?'; params=[perfil]
    counts=Counter(); recent={}
    for row in conexion_db.execute(sql,params):
        etiquetas=row['etiquetas'] if hasattr(row,'keys') else row[0]
        if not etiquetas: continue
        tags=normalizar(etiquetas)
        if not tags: continue
        accessed=row['ultimo_acceso'] if hasattr(row,'keys') else row[1]
        hidden=row['recent_hidden'] if hasattr(row,'keys') else row[2]
        added=row['fecha_agregado'] if hasattr(row,'keys') else row[3]
        item_time=(accessed if (accessed and not hidden) else '') or (added or '')
        for tag in tags:
            counts[tag]+=1
            if item_time and item_time>recent.get(tag,''):
                recent[tag]=item_time
    return [dict(tag=tag,total=total,recent=recent.get(tag,'')) for tag,total in counts.items()]

class TagsManager:
    def __init__(self, db): self.db=db
    def actualizar_etiquetas_item(self, drive_id, nuevas_etiquetas):
        from .library_layout import root_id, move_primary, category_name
        row=self.db.execute('SELECT * FROM items WHERE drive_id=?',(drive_id,)).fetchone()
        if not row:return False
        tags=normalizar(nuevas_etiquetas)
        linked=bool(root_id(self.db,row['perfil_drive']))
        if linked and tags and not row['container_parent']:category_name(tags[0])
        if linked and row['disponible'] and not row['container_parent']:
            move_primary(self.db,dict(row),tags)
            return True
        with self.db:
            return self.db.execute('UPDATE items SET etiquetas=? WHERE drive_id=?',(' '.join('+'+t for t in tags),drive_id)).rowcount>0
    def asignar_etiquetas_en_lote(self, lista_drive_ids, etiqueta, accion='agregar'):
        tags=normalizar(etiqueta)
        if len(tags)!=1 or accion not in ('agregar','quitar'): raise ValueError('Etiqueta o acción inválida')
        from .library_layout import root_id, preflight_moves
        changes=[]
        for ident in dict.fromkeys(lista_drive_ids):
            row=self.db.execute('SELECT * FROM items WHERE drive_id=?',(ident,)).fetchone()
            if not row: continue
            values=normalizar(row['etiquetas'])
            if accion=='agregar' and tags[0] not in values: values.append(tags[0])
            if accion=='quitar': values=[value for value in values if value!=tags[0]]
            changes.append((dict(row),values))
        for profile in {item['perfil_drive'] for item,_ in changes}:
            if root_id(self.db,profile):
                preflight_moves(self.db,[(item,values) for item,values in changes if item['perfil_drive']==profile])
        for item,values in changes:
            self.actualizar_etiquetas_item(item['drive_id'],' '.join('+'+tag for tag in values))
        return len(changes)
