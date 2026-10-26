import itertools
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from core.database import conectar, configurar
from core.drive_sync import DriveSync, extraer_ids_proto, conectar_db_drive_ro
from core.items_manager import ItemsManager
from core.search_parser import agregar_filtro, limpiar_todos_filtros, buscar, buscar_global
from core.tags_manager import TagsManager, obtener_etiquetas_ordenadas_frecuencia
from core.serendipity import obtener_semi_aleatorio_contextual
from core.backup_manager import crear_backup_en_drive
from core.cleaner import limpiar_biblioteca_db
from core.desktop_api import DesktopAPI


def proto(ident, parent=None):
    value=ident.encode(); result=bytes([10,len(value)])+value
    if parent:
        value=parent.encode(); result+=bytes([18,len(value)])+value
    return result

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.db=conectar(self.root/'biblioteca.db')
        self.source=self.root/'metadata_sqlite_db'
        c=sqlite3.connect(self.source)
        c.executescript('CREATE TABLE items(stable_id INTEGER PRIMARY KEY, local_title TEXT,is_folder INT,mime_type TEXT,file_size INT,trashed INT,proto BLOB); CREATE TABLE stable_parents(item_stable_id INT,parent_stable_id INT);')
        for i,title,folder,parent in [(1,'Mi unidad',1,None),(2,'Biblioteca',1,1),(3,'Historia',1,2),(4,'Roma.pdf',0,3),(5,'.balisco_backup',1,2),(6,'secreto.pdf',0,5),(7,'Curso Blender',1,11),(8,'capitulo.mp4',0,7),(9,'.oculto',1,2),(10,'oculto.pdf',0,9),(11,'Containers',1,2)]:
            ident='drive_id_'+str(i).zfill(3)
            c.execute('INSERT INTO items VALUES(?,?,?,?,?,?,?)',(i,title,folder,'application/pdf',100,0,proto(ident)))
            if parent: c.execute('INSERT INTO stable_parents VALUES(?,?)',(i,parent))
        c.commit(); c.close()
        self.sync=DriveSync(self.db); self.run_sync()
        self.manager=ItemsManager(self.db)
    def tearDown(self): self.db.close(); self.temp.cleanup()
    def run_sync(self): return self.sync.sincronizar_biblioteca(ruta_db=self.source,perfil='fixture')
    def test_exclusions_and_course_boundary(self):
        self.assertEqual([r[0] for r in self.db.execute('SELECT titulo FROM items ORDER BY titulo')],['Curso Blender','Roma','capitulo'])
        self.assertEqual([r['titulo'] for r in buscar(self.db,limpiar_todos_filtros())],['Curso Blender','Roma'])
        self.assertEqual(self.db.execute("SELECT categoria_macro FROM items WHERE tipo='pdf'").fetchone()[0],'Historia')
    def test_document_type_and_epub_format_are_independent(self):
        source=sqlite3.connect(self.source)
        source.execute('INSERT INTO items VALUES(?,?,?,?,?,?,?)',
                       (12,'Fundamental Accessibility Tests.epub',0,'application/epub+zip',256,0,proto('drive_id_012')))
        source.execute('INSERT INTO stable_parents VALUES(?,?)',(12,3))
        source.commit(); source.close()
        self.run_sync()
        item=self.manager.obtener('drive_id_012')
        self.assertEqual((item['tipo_contenido'],item['formato']),('documento','EPUB'))
        filters=agregar_filtro('@tipo:documento',limpiar_todos_filtros())
        self.assertEqual({row['drive_id'] for row in buscar(self.db,filters,perfil='fixture')},
                         {'drive_id_004','drive_id_012'})
    def test_sync_preserves_metadata_and_repairs_path(self):
        self.manager.actualizar_notas('drive_id_004','Mi apunte único')
        self.manager.cambiar_rating('drive_id_004',5)
        self.manager.cambiar_titulo('drive_id_004','Mi Roma')
        c=sqlite3.connect(self.source); c.execute("UPDATE items SET local_title='Roma nueva.pdf' WHERE stable_id=4"); c.commit(); c.close()
        self.run_sync(); item=self.manager.obtener('drive_id_004')
        self.assertEqual(item['titulo'],'Mi Roma'); self.assertEqual(item['rating'],5)
        self.assertIn('Roma nueva.pdf',item['ruta_relativa']); self.assertEqual(item['notas'],'Mi apunte único')
    def test_reuploaded_pdf_at_same_path_keeps_library_identity(self):
        old_id,new_id='drive_id_004','drive_id_012'
        original=self.manager.obtener(old_id)
        self.manager.actualizar_notas(old_id,'Notas que deben continuar')
        self.manager.cambiar_rating(old_id,4)
        self.manager.cambiar_titulo(old_id,'Roma anotada')
        self.manager.cambiar_favorito(old_id,1)
        TagsManager(self.db).actualizar_etiquetas_item(old_id,'+historia')
        covers=self.root/'portadas';covers.mkdir()
        (covers/(old_id+'.jpg')).write_bytes(b'portada')
        source=sqlite3.connect(self.source)
        source.execute('UPDATE items SET trashed=1 WHERE stable_id=4')
        source.execute('INSERT INTO items VALUES(?,?,?,?,?,?,?)',
                       (12,'Roma.pdf',0,'application/pdf',250,0,proto(new_id)))
        source.execute('INSERT INTO stable_parents VALUES(?,?)',(12,3))
        source.commit();source.close()
        self.run_sync()
        item=self.manager.obtener(new_id)
        self.assertEqual((item['id'],item['notas'],item['rating'],item['titulo'],item['es_favorito'],item['etiquetas'],item['tamano_bytes']),
                         (original['id'],'Notas que deben continuar',4,'Roma anotada',1,'+historia',250))
        self.assertEqual((covers/(new_id+'.jpg')).read_bytes(),b'portada')
        with self.assertRaises(KeyError):self.manager.obtener(old_id)
        self.run_sync()
        self.assertEqual(self.manager.obtener(new_id)['id'],original['id'])
    def test_relink_does_not_guess_when_old_or_new_paths_are_ambiguous(self):
        old_id='drive_id_004'
        self.manager.actualizar_notas(old_id,'No copiar a un archivo ambiguo')
        with self.db:
            self.db.execute('''INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive,disponible,notas)
                VALUES('drive_old_copy','Roma','pdf',?,'fixture',0,'Otra tarjeta')''',
                (self.manager.obtener(old_id)['ruta_relativa'],))
        source=sqlite3.connect(self.source)
        source.execute('UPDATE items SET trashed=1 WHERE stable_id=4')
        source.execute('INSERT INTO items VALUES(?,?,?,?,?,?,?)',
                       (12,'Roma.pdf',0,'application/pdf',100,0,proto('drive_id_012')))
        source.execute('INSERT INTO stable_parents VALUES(?,?)',(12,3))
        source.commit();source.close()
        self.run_sync()
        self.assertEqual(self.manager.obtener('drive_id_012')['notas'],'')
        self.assertEqual(self.manager.obtener(old_id)['notas'],'No copiar a un archivo ambiguo')
    def test_same_name_does_not_relink_while_original_still_exists(self):
        self.manager.actualizar_notas('drive_id_004','Solo el original')
        source=sqlite3.connect(self.source)
        source.execute('INSERT INTO items VALUES(?,?,?,?,?,?,?)',
                       (12,'Roma.pdf',0,'application/pdf',100,0,proto('drive_id_012')))
        source.execute('INSERT INTO stable_parents VALUES(?,?)',(12,3))
        source.commit();source.close()
        self.run_sync()
        self.assertEqual(self.manager.obtener('drive_id_004')['notas'],'Solo el original')
        self.assertEqual(self.manager.obtener('drive_id_012')['notas'],'')
    def test_relink_waits_for_vanished_old_id_then_merges_new_row(self):
        old_id,new_id='drive_id_004','drive_id_012'
        original=self.manager.obtener(old_id)
        self.manager.actualizar_notas(old_id,'Vuelve cuando el anterior desaparezca')
        source=sqlite3.connect(self.source)
        source.execute('UPDATE stable_parents SET parent_stable_id=1 WHERE item_stable_id=4')
        source.execute('INSERT INTO items VALUES(?,?,?,?,?,?,?)',
                       (12,'Roma.pdf',0,'application/pdf',250,0,proto(new_id)))
        source.execute('INSERT INTO stable_parents VALUES(?,?)',(12,3))
        source.commit();source.close()
        self.run_sync()
        self.assertEqual(self.manager.obtener(new_id)['notas'],'')
        self.assertEqual(self.manager.obtener(old_id)['notas'],'Vuelve cuando el anterior desaparezca')
        source=sqlite3.connect(self.source)
        source.execute('UPDATE items SET trashed=1 WHERE stable_id=4')
        source.commit();source.close()
        self.run_sync()
        self.assertEqual(self.manager.obtener(new_id)['id'],original['id'])
        self.assertEqual(self.manager.obtener(new_id)['notas'],'Vuelve cuando el anterior desaparezca')
        with self.assertRaises(KeyError):self.manager.obtener(old_id)
    def test_two_new_pdfs_at_same_path_do_not_relink(self):
        self.manager.actualizar_notas('drive_id_004','No asignar a dos candidatos')
        source=sqlite3.connect(self.source)
        source.execute('UPDATE items SET trashed=1 WHERE stable_id=4')
        for stable_id in (12,13):
            source.execute('INSERT INTO items VALUES(?,?,?,?,?,?,?)',
                           (stable_id,'Roma.pdf',0,'application/pdf',100,0,proto('drive_id_'+str(stable_id).zfill(3))))
            source.execute('INSERT INTO stable_parents VALUES(?,?)',(stable_id,3))
        source.commit();source.close()
        self.run_sync()
        self.assertEqual(self.manager.obtener('drive_id_012')['notas'],'')
        self.assertEqual(self.manager.obtener('drive_id_013')['notas'],'')
        self.assertEqual(self.manager.obtener('drive_id_004')['notas'],'No asignar a dos candidatos')
    def test_reuploaded_pdf_inside_container_keeps_parent_and_properties(self):
        source=sqlite3.connect(self.source)
        source.execute('INSERT INTO items VALUES(?,?,?,?,?,?,?)',
                       (12,'Lección.pdf',0,'application/pdf',100,0,proto('drive_id_012')))
        source.execute('INSERT INTO stable_parents VALUES(?,?)',(12,7))
        source.commit();source.close()
        self.run_sync()
        original=self.manager.obtener('drive_id_012')
        self.manager.actualizar_notas('drive_id_012','Nota del contenedor')
        source=sqlite3.connect(self.source)
        source.execute('UPDATE items SET trashed=1 WHERE stable_id=12')
        source.execute('INSERT INTO items VALUES(?,?,?,?,?,?,?)',
                       (13,'Lección.pdf',0,'application/pdf',120,0,proto('drive_id_013')))
        source.execute('INSERT INTO stable_parents VALUES(?,?)',(13,7))
        source.commit();source.close()
        self.run_sync()
        item=self.manager.obtener('drive_id_013')
        self.assertEqual((item['id'],item['notas'],item['container_parent']),
                         (original['id'],'Nota del contenedor','drive_id_007'))
        self.assertEqual(self.db.execute('SELECT container_drive_id FROM container_entries WHERE drive_id=?',
                                         ('drive_id_013',)).fetchone()[0],'drive_id_007')
        self.assertIsNone(self.db.execute('SELECT 1 FROM container_entries WHERE drive_id=?',
                                          ('drive_id_012',)).fetchone())
    def test_deleted_pdf_keeps_hidden_metadata_for_later_upload(self):
        from pathlib import PureWindowsPath
        item=self.manager.obtener('drive_id_004')
        path=self.root.joinpath(*PureWindowsPath(item['ruta_relativa']).parts)
        path.parent.mkdir(parents=True);path.write_bytes(b'pdf')
        with self.db:configurar(self.db,'unidad_drive:fixture',str(self.root))
        self.manager.actualizar_notas(item['drive_id'],'Recuperar al subir otra copia')
        with patch('send2trash.send2trash'):
            self.manager.eliminar_item(item['drive_id'])
        self.assertEqual(self.manager.obtener(item['drive_id'])['disponible'],0)
        self.assertEqual(self.manager.obtener(item['drive_id'])['notas'],'Recuperar al subir otra copia')
        pending=self.db.execute('SELECT expected_relative,container_drive_id FROM pending_container_moves WHERE drive_id=?',
                                (item['drive_id'],)).fetchone()
        self.assertEqual(tuple(pending),(item['ruta_relativa'],'__removed__'))
        source=sqlite3.connect(self.source)
        source.execute('INSERT INTO items VALUES(?,?,?,?,?,?,?)',
                       (12,'Roma.pdf',0,'application/pdf',100,0,proto('drive_id_012')))
        source.execute('INSERT INTO stable_parents VALUES(?,?)',(12,3))
        source.commit();source.close()
        self.run_sync()
        self.assertEqual(self.manager.obtener('drive_id_012')['notas'],'Recuperar al subir otra copia')
    def test_recreated_pdf_with_same_drive_id_reappears_after_app_delete(self):
        from pathlib import PureWindowsPath
        item=self.manager.obtener('drive_id_004')
        path=self.root.joinpath(*PureWindowsPath(item['ruta_relativa']).parts)
        path.parent.mkdir(parents=True);path.write_bytes(b'pdf')
        with self.db:configurar(self.db,'unidad_drive:fixture',str(self.root))
        self.manager.actualizar_notas(item['drive_id'],'Conservar con el mismo ID')
        with patch('send2trash.send2trash'):
            self.manager.eliminar_item(item['drive_id'])
        self.run_sync()
        self.assertEqual(self.manager.obtener(item['drive_id'])['disponible'],1)
        self.assertEqual(self.manager.obtener(item['drive_id'])['notas'],'Conservar con el mismo ID')
        self.assertIsNone(self.db.execute('SELECT 1 FROM pending_container_moves WHERE drive_id=?',
                                          (item['drive_id'],)).fetchone())
    def test_repeat_sync_does_not_rewrite_unchanged_items(self):
        with self.db:
            self.db.execute('CREATE TABLE sync_audit(id TEXT)')
            self.db.execute('''CREATE TRIGGER sync_audit_items AFTER UPDATE ON items BEGIN
                INSERT INTO sync_audit VALUES(old.drive_id); END''')
        self.run_sync()
        self.assertEqual(self.db.execute('SELECT count(*) FROM sync_audit').fetchone()[0],0)
    def test_trashed_is_hidden_but_notes_retained(self):
        self.manager.actualizar_notas('drive_id_004','persistir')
        c=sqlite3.connect(self.source); c.execute('UPDATE items SET trashed=1 WHERE stable_id=3'); c.commit(); c.close()
        self.run_sync()
        self.assertEqual(self.manager.obtener('drive_id_004')['disponible'],0)
        self.assertEqual(self.manager.obtener('drive_id_004')['notas'],'persistir')
    def test_order_independence_exact_tags_fts(self):
        TagsManager(self.db).actualizar_etiquetas_item('drive_id_004','+Historia +romano')
        self.manager.cambiar_rating('drive_id_004',4)
        for tokens in itertools.permutations(['+historia','-novela','Roma','@pendiente','@rating:4']):
            f=limpiar_todos_filtros()
            for token in tokens: f=agregar_filtro(token,f)
            self.assertEqual(len(buscar(self.db,f)),1)
        f=agregar_filtro('+roma',limpiar_todos_filtros()); self.assertEqual(buscar(self.db,f),[])
        f=agregar_filtro('" OR 1=1 --',limpiar_todos_filtros()); self.assertEqual(buscar(self.db,f),[])
    def test_author_unified_search_and_update(self):
        self.manager.cambiar_autor('drive_id_004','Michel Lauricella')
        item=self.manager.obtener('drive_id_004')
        self.assertEqual(item['autor'],'Michel Lauricella')
        f=agregar_filtro('Lauricella',limpiar_todos_filtros())
        results=buscar(self.db,f)
        self.assertEqual(len(results),1)
        self.assertEqual(results[0]['drive_id'],'drive_id_004')
        self.assertEqual(len(buscar_global(self.db,'lauricella')),1)
    def test_search_accepts_partial_words_while_typing(self):
        self.manager.cambiar_autor('drive_id_004','Michel Lauricella')
        for text in ('Lauri','Rom','Michel Lau'):
            filters=agregar_filtro(text,limpiar_todos_filtros())
            self.assertEqual([item['drive_id'] for item in buscar(self.db,filters)],['drive_id_004'])
        self.manager.cambiar_titulo('drive_id_004','Análisis dimensional')
        for text in ('anali','analisi','analisis','análisis','DIMENS'):
            filters=agregar_filtro(text,limpiar_todos_filtros())
            self.assertEqual([item['drive_id'] for item in buscar(self.db,filters)],['drive_id_004'])
    def test_favorite_and_authors_survive_sync(self):
        self.manager.cambiar_autor('drive_id_004','Ana Torres\nLuis Vega')
        self.manager.cambiar_favorito('drive_id_004',1)
        self.run_sync()
        item=self.manager.obtener('drive_id_004')
        self.assertEqual(item['autor'],'Ana Torres\nLuis Vega')
        self.assertEqual(item['es_favorito'],1)
    def test_manual_authors_survive_title_cleaning(self):
        with self.db: self.db.execute("UPDATE items SET titulo='Nuevo Autor - Roma.pdf' WHERE drive_id='drive_id_004'")
        self.manager.cambiar_autor('drive_id_004','Ana Torres\nLuis Vega')
        limpiar_biblioteca_db(self.db)
        self.assertEqual(self.manager.obtener('drive_id_004')['autor'],'Ana Torres\nLuis Vega')
    def test_notes_fts_update_delete(self):
        self.manager.actualizar_notas('drive_id_004','astronomía')
        self.assertEqual(len(buscar_global(self.db,'astronomia')),1)
        self.manager.actualizar_notas('drive_id_004','biología')
        self.assertEqual(buscar_global(self.db,'astronomia'),[])
        with self.db: self.db.execute("DELETE FROM items WHERE drive_id='drive_id_004'")
        self.assertEqual(buscar_global(self.db,'biologia'),[])
    def test_tags_and_context(self):
        tags=TagsManager(self.db)
        tags.asignar_etiquetas_en_lote(['drive_id_004','drive_id_007'],'+arte')
        self.assertEqual(obtener_etiquetas_ordenadas_frecuencia(self.db),[dict(tag='arte',total=2)])
        with self.db: self.db.execute("UPDATE items SET ultimo_acceso=CURRENT_TIMESTAMP,estado_lectura='leido' WHERE drive_id='drive_id_004'")
        self.assertEqual(obtener_semi_aleatorio_contextual(self.db)['drive_id'],'drive_id_007')
    def test_tag_suggestions_recency(self):
        from core.tags_manager import obtener_sugerencias_etiquetas
        tags=TagsManager(self.db)
        tags.asignar_etiquetas_en_lote(['drive_id_004'],'+historia')
        tags.asignar_etiquetas_en_lote(['drive_id_007'],'+diseno')
        with self.db:
            self.db.execute("UPDATE items SET ultimo_acceso='2026-01-01 10:00:00' WHERE drive_id='drive_id_004'")
            self.db.execute("UPDATE items SET ultimo_acceso='2026-10-25 12:00:00' WHERE drive_id='drive_id_007'")
        suggs = {s['tag']: s for s in obtener_sugerencias_etiquetas(self.db)}
        self.assertEqual(suggs['diseno']['recent'], '2026-10-25 12:00:00')
        self.assertEqual(suggs['historia']['recent'], '2026-01-01 10:00:00')
    def test_advanced_filter_combinations(self):
        with self.db:
            self.db.execute("UPDATE items SET rating=4, tamano_bytes=100000000, estado_lectura='leyendo', formato='PDF', notas='Importante' WHERE drive_id='drive_id_004'")
            self.db.execute("UPDATE items SET rating=2, tamano_bytes=5000000, estado_lectura='leido', formato='EPUB', notas='' WHERE drive_id='drive_id_007'")
        tags = TagsManager(self.db)
        tags.asignar_etiquetas_en_lote(['drive_id_004'], '+historia')
        tags.asignar_etiquetas_en_lote(['drive_id_007'], '+ciencia')
        
        # Test rating range & gte
        f = agregar_filtro('@rating:3-5', limpiar_todos_filtros())
        self.assertEqual([r['drive_id'] for r in buscar(self.db, f)], ['drive_id_004'])
        f = agregar_filtro('@rating:>=4', limpiar_todos_filtros())
        self.assertEqual([r['drive_id'] for r in buscar(self.db, f)], ['drive_id_004'])
        
        # Test format
        f = agregar_filtro('@formato:pdf,epub', limpiar_todos_filtros())
        self.assertCountEqual([r['drive_id'] for r in buscar(self.db, f)], ['drive_id_004', 'drive_id_007'])
        
        # Test size
        f = agregar_filtro('@peso:>50mb', limpiar_todos_filtros())
        self.assertEqual([r['drive_id'] for r in buscar(self.db, f)], ['drive_id_004'])
        f = agregar_filtro('@peso:<10mb', limpiar_todos_filtros())
        self.assertEqual([r['drive_id'] for r in buscar(self.db, f)], ['drive_id_007'])
        
        # Test sin_portada and con_portada parsing
        f = agregar_filtro('@sin:miniatura', limpiar_todos_filtros())
        self.assertTrue(any(p['tipo'] == 'sin_portada' for p in f['pildoras']))
        f = agregar_filtro('@con:miniatura', limpiar_todos_filtros())
        self.assertTrue(any(p['tipo'] == 'con_portada' for p in f['pildoras']))
        f = agregar_filtro('@sin:portada', limpiar_todos_filtros())
        self.assertTrue(any(p['tipo'] == 'sin_portada' for p in f['pildoras']))
        f = agregar_filtro('@con:portada', limpiar_todos_filtros())
        self.assertTrue(any(p['tipo'] == 'con_portada' for p in f['pildoras']))

        # Test state exclusion
        f = agregar_filtro('@!leido', limpiar_todos_filtros())
        self.assertEqual([r['drive_id'] for r in buscar(self.db, f)], ['drive_id_004'])
        
        # Test tag OR
        f = agregar_filtro('+historia|ciencia', limpiar_todos_filtros())
        self.assertCountEqual([r['drive_id'] for r in buscar(self.db, f)], ['drive_id_004', 'drive_id_007'])
        
        # Test maintenance filters
        f = agregar_filtro('@con:notas', limpiar_todos_filtros())
        self.assertEqual([r['drive_id'] for r in buscar(self.db, f)], ['drive_id_004'])
        f = agregar_filtro('@sin:notas', limpiar_todos_filtros())
        self.assertEqual([r['drive_id'] for r in buscar(self.db, f)], ['drive_id_007'])
    def test_unnamed_course_with_video(self):
        c=sqlite3.connect(self.source); c.execute("UPDATE items SET local_title='Blender 3D' WHERE stable_id=7"); c.commit(); c.close()
        self.run_sync()
        self.assertEqual(self.manager.obtener('drive_id_007')['tipo'],'curso')
        self.assertEqual(self.db.execute("SELECT container_drive_id FROM container_entries WHERE drive_id='drive_id_008'").fetchone()[0],'drive_id_007')
        self.assertNotIn('drive_id_008',[r['drive_id'] for r in buscar(self.db,limpiar_todos_filtros())])
    def test_deep_search_switch_and_nested_titles(self):
        c=sqlite3.connect(self.source)
        c.execute('INSERT INTO items VALUES(?,?,?,?,?,?,?)',(12,'Materials',1,'application/octet-stream',0,0,proto('drive_id_012')))
        c.execute('INSERT INTO stable_parents VALUES(?,?)',(12,7))
        c.execute('INSERT INTO items VALUES(?,?,?,?,?,?,?)',(13,'Mort.pdf',0,'application/pdf',100,0,proto('drive_id_013')))
        c.execute('INSERT INTO stable_parents VALUES(?,?)',(13,12))
        c.commit(); c.close(); self.run_sync()
        filters=agregar_filtro('Mort',limpiar_todos_filtros())
        self.assertEqual(buscar(self.db,filters),[])
        api=DesktopAPI(self.root)
        self.assertTrue(api.call('set_deep_search',{'id':'drive_id_007','enabled':True})['ok'])
        self.assertEqual([r['drive_id'] for r in buscar(self.db,filters)],['drive_id_013'])
        self.assertEqual(self.db.execute("SELECT count(*) FROM items WHERE drive_id='drive_id_013'").fetchone()[0],1)
        c=sqlite3.connect(self.source)
        c.execute("UPDATE items SET local_title='Ritos iguales.pdf' WHERE stable_id=13")
        c.commit(); c.close(); self.run_sync()
        self.assertEqual(buscar(self.db,filters),[])
        self.assertEqual([r['drive_id'] for r in buscar(self.db,agregar_filtro('Ritos',limpiar_todos_filtros()))],['drive_id_013'])
        self.assertTrue(api.call('set_deep_search',{'id':'drive_id_007','enabled':False})['ok'])
        self.assertEqual(buscar(self.db,agregar_filtro('Ritos',limpiar_todos_filtros())),[])
    def test_pending_move_survives_stale_drive_metadata(self):
        with self.db:
            self.db.execute("UPDATE items SET disponible=0 WHERE drive_id='drive_id_004'")
            self.db.execute("INSERT INTO container_entries(container_drive_id,drive_id,titulo,ruta_relativa,perfil_drive) VALUES('drive_id_007','drive_id_004','Roma.pdf',?, 'fixture')",(r'Mi unidad\Biblioteca\Containers\Curso Blender\Roma.pdf',))
            self.db.execute("INSERT INTO pending_container_moves(drive_id,expected_relative,container_drive_id,perfil_drive) VALUES('drive_id_004',?,'drive_id_007','fixture')",(r'Mi unidad\Biblioteca\Containers\Curso Blender\Roma.pdf',))
        self.run_sync()
        self.assertEqual(self.manager.obtener('drive_id_004')['disponible'],0)
        self.assertEqual(self.db.execute("SELECT container_drive_id FROM container_entries WHERE drive_id='drive_id_004'").fetchone()[0],'drive_id_007')
    def test_remote_title_refresh(self):
        c=sqlite3.connect(self.source); c.execute("UPDATE items SET local_title='Roma nueva.pdf' WHERE stable_id=4"); c.commit(); c.close()
        self.run_sync()
        self.assertEqual(self.manager.obtener('drive_id_004')['titulo'],'Roma nueva')
    def test_invalid_rating(self):
        for value in [-1,6,True,2.5]:
            with self.assertRaises(ValueError): self.manager.cambiar_rating('drive_id_004',value)
    def test_proto_and_readonly(self):
        self.assertEqual(extraer_ids_proto(proto('drive_id_004','drive_id_003')),('drive_id_004',['drive_id_003']))
        with self.assertRaises(ValueError): extraer_ids_proto(b'\x0a\xff')
        c=conectar_db_drive_ro(self.source)
        try:
            with self.assertRaises(sqlite3.OperationalError): c.execute('DELETE FROM items')
        finally: c.close()
    def test_backup_snapshot(self):
        (self.root/'Mi unidad'/'Biblioteca').mkdir(parents=True)
        (self.root/'portadas').mkdir(); (self.root/'portadas'/'drive_id_004.jpg').write_bytes(b'test-cover')
        target=crear_backup_en_drive(self.root,self.db,self.root)
        with zipfile.ZipFile(target) as z:
            self.assertEqual(set(z.namelist()),{'biblioteca.db','portadas/drive_id_004.jpg'})
            extracted=self.root/'restored'; z.extractall(extracted)
        c=sqlite3.connect(extracted/'biblioteca.db')
        self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        self.assertEqual(c.execute('SELECT COUNT(*) FROM items').fetchone()[0],3); c.close()

if __name__=='__main__': unittest.main()
