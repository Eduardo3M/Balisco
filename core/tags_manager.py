from collections import Counter

def normalizar(texto):
    return sorted({t.lstrip('+').casefold() for t in texto.split() if t.lstrip('+')})

def obtener_etiquetas_ordenadas_frecuencia(conexion_db, perfil=None):
    sql='SELECT etiquetas FROM items WHERE disponible=1'; params=[]
    if perfil is not None: sql+=' AND perfil_drive=?'; params=[perfil]
    counts=Counter(t for row in conexion_db.execute(sql,params) for t in normalizar(row[0]))
    return [dict(tag=t,total=n) for t,n in sorted(counts.items(),key=lambda x:(-x[1],x[0]))]

class TagsManager:
    def __init__(self, db): self.db=db
    def actualizar_etiquetas_item(self, drive_id, nuevas_etiquetas):
        with self.db:
            return self.db.execute('UPDATE items SET etiquetas=? WHERE drive_id=?',(' '.join('+'+t for t in normalizar(nuevas_etiquetas)),drive_id)).rowcount>0
    def asignar_etiquetas_en_lote(self, lista_drive_ids, etiqueta, accion='agregar'):
        tags=normalizar(etiqueta)
        if len(tags)!=1 or accion not in ('agregar','quitar'): raise ValueError('Etiqueta o acción inválida')
        total=0
        with self.db:
            for ident in set(lista_drive_ids):
                row=self.db.execute('SELECT etiquetas FROM items WHERE drive_id=?',(ident,)).fetchone()
                if not row: continue
                values=set(normalizar(row[0]))
                values.add(tags[0]) if accion=='agregar' else values.discard(tags[0])
                self.db.execute('UPDATE items SET etiquetas=? WHERE drive_id=?',(' '.join('+'+t for t in sorted(values)),ident)); total+=1
        return total
