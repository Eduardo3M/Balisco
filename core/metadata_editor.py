"""Profile-scoped taxonomy edits. Item metadata remains the source of truth."""
from .tags_manager import normalizar


def edit_taxonomy(db, profile, kind, operation, old, new=''):
    if kind not in ('tag','author') or operation not in ('rename','delete'):
        raise ValueError('Edición de metadatos inválida')
    old=str(old).strip(); new=str(new).strip()
    if not old or (operation=='rename' and not new):
        raise ValueError('Nombre vacío')
    if kind=='tag':
        old=old.lstrip('+').casefold(); new=new.lstrip('+').casefold()
        if len(normalizar(old))!=1 or (operation=='rename' and len(normalizar(new))!=1):
            raise ValueError('Etiqueta inválida')
    elif '\n' in old or '\n' in new or '\r' in old or '\r' in new:
        raise ValueError('Autor inválido')
    field='etiquetas' if kind=='tag' else 'autor'
    rows=db.execute('SELECT id,'+field+' FROM items WHERE perfil_drive=?',(profile,)).fetchall()
    changes=[]
    for row in rows:
        if kind=='tag':
            names=set(normalizar(row[field]))
            if old not in names: continue
            names.remove(old)
            if operation=='rename': names.add(new)
            value=' '.join('+'+name for name in sorted(names))
        else:
            names=[name.strip() for name in row[field].splitlines() if name.strip()]
            if not any(name.casefold()==old.casefold() for name in names): continue
            names=[new if name.casefold()==old.casefold() and operation=='rename' else name
                   for name in names if name.casefold()!=old.casefold() or operation=='rename']
            value='\n'.join(dict.fromkeys(names))
        changes.append((value,row['id']))
    with db: db.executemany('UPDATE items SET '+field+'=? WHERE id=?',changes)
    return {'updated':len(changes)}
