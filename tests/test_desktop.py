import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from io import BytesIO
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from core.database import conectar, configurar
from core.desktop_api import DesktopAPI
from core.migrations import migrate_author

class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        with closing(conectar(self.root/'biblioteca.db')) as db:
            with db:
                configurar(db,'id_perfil_drive','test')
                db.executemany("INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive) VALUES(?,?,?,?,?)",[
                    ('test_drive_001','Libro <script>','pdf',r'Mi unidad\Biblioteca\book.pdf','test'),
                    ('test_drive_002','Otro libro','pdf',r'Mi unidad\Biblioteca\other.pdf','other')])
        self.api=DesktopAPI(self.root)
    def tearDown(self): self.temp.cleanup()
    def call(self,action,**data):
        result=self.api.call(action,data); self.assertTrue(result['ok'],result); return result['data']
    def test_profile_boundary(self):
        self.assertEqual(len(self.call('query')['items']),1)
        self.assertFalse(self.api.call('detail',{'id':'test_drive_002'})['ok'])
        self.assertFalse(self.api.call('update',{'id':'test_drive_002','field':'rating','value':5})['ok'])
    @unittest.skipUnless(os.name=='nt','La restauración usa la papelera de Windows')
    def test_delete_undo_restores_each_file_and_metadata(self):
        folder=self.root/'Mi unidad'/'Biblioteca'
        folder.mkdir(parents=True)
        first=folder/'book.pdf'; second=folder/'third.pdf'
        first.write_bytes(b'first'); second.write_bytes(b'second')
        with closing(self.api._connect()) as db:
            with db:
                configurar(db,'unidad_drive:test',str(self.root))
                db.execute("UPDATE items SET notas='nota recuperable',rating=4 WHERE drive_id='test_drive_001'")
                db.execute("INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive) VALUES('test_drive_003','Tercero','pdf',?, 'test')",(r'Mi unidad\Biblioteca\third.pdf',))
        self.call('preference',key='confirm_delete',value='false')
        self.assertEqual(self.call('bootstrap')['prefs']['confirm_delete'],'false')
        self.call('delete_item',id='test_drive_001')
        self.call('delete_item',id='test_drive_003')
        self.assertFalse(first.exists());self.assertFalse(second.exists())
        self.assertEqual(self.call('undo_delete')['name'],'third.pdf')
        self.assertTrue(second.exists());self.assertFalse(first.exists())
        self.assertEqual(self.call('undo_delete')['name'],'book.pdf')
        self.assertEqual(first.read_bytes(),b'first')
        self.assertEqual(self.call('detail',id='test_drive_001')['notas'],'nota recuperable')
        self.assertEqual(self.call('detail',id='test_drive_001')['rating'],4)
        self.assertFalse(self.call('undo_delete')['restored'])
    @unittest.skipUnless(os.name=='nt','La restauración usa la papelera de Windows')
    def test_undo_container_folder_restores_index_and_files(self):
        folder=self.root/'Mi unidad'/'Biblioteca'/'Containers'/'Course'/'Section'
        folder.mkdir(parents=True)
        file=folder/'lesson.pdf';file.write_bytes(b'lesson')
        relative=r'Mi unidad\Biblioteca\Containers\Course'
        with closing(self.api._connect()) as db:
            with db:
                configurar(db,'unidad_drive:test',str(self.root))
                db.execute("INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive) VALUES('test_container','Course','curso',?,'test')",(relative,))
                db.execute("INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive,container_parent,notas) VALUES('test_lesson','Lesson','pdf',?,'test','test_container','recordar')",(relative+r'\Section\lesson.pdf',))
                db.execute("INSERT INTO container_entries(container_drive_id,drive_id,titulo,ruta_relativa,perfil_drive) VALUES('test_container','test_lesson','lesson.pdf',?,'test')",(relative+r'\Section\lesson.pdf',))
        records={'folder_section':{'id':'folder_section','title':'Section','path':relative+r'\Section','folder':True},
                 'test_lesson':{'id':'test_lesson','title':'Section/lesson.pdf','path':relative+r'\Section\lesson.pdf','size':6,'mime':'application/pdf'}}
        original=self.api._dispatch
        def dispatch(db,action,payload):
            if action=='container':
                self.api._containers[payload['id']]=records.copy()
                return list(records.values())
            return original(db,action,payload)
        with patch.object(self.api,'_dispatch',side_effect=dispatch):
            self.assertEqual(self.call('container_trash_folder',container='test_container',path=['Section'])['deleted'],1)
        self.assertFalse(folder.exists())
        self.assertEqual(self.call('undo_delete')['name'],'Section')
        self.assertEqual(file.read_bytes(),b'lesson')
        self.assertEqual(self.call('detail',id='test_lesson')['notas'],'recordar')
        with closing(self.api._connect()) as db:
            self.assertIsNotNone(db.execute("SELECT 1 FROM container_entries WHERE drive_id='test_lesson'").fetchone())
            self.assertIsNone(db.execute("SELECT 1 FROM pending_container_moves WHERE drive_id='test_lesson'").fetchone())
    def test_author_notes_fts(self):
        self.call('update',id='test_drive_001',field='autor',value='Lauricella')
        self.assertEqual(len(self.call('query',tokens=['Lauricella'])['items']),1)
        self.call('update',id='test_drive_001',field='notas',value='morfología')
        self.assertEqual(len(self.call('query',tokens=['morfologia'])['items']),1)
        self.assertFalse(self.api.call('update',{'id':'test_drive_001','field':'drive_id','value':'bad'})['ok'])
    def test_author_browser_search_and_bulk_metadata(self):
        with closing(sqlite3.connect(self.root/'biblioteca.db')) as db:
            db.execute("INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive) VALUES(?,?,?,?,?)",('test_drive_003','Tercer libro','pdf','third.pdf','test'))
            db.commit()
        self.call('update',id='test_drive_001',field='autor',value='Ana Torres')
        self.call('update',id='test_drive_001',field='etiquetas',value='+historia')
        self.call('update',id='test_drive_003',field='autor',value='Luis Vega')
        ids=['test_drive_001','test_drive_003']
        self.assertEqual(self.call('bulk_metadata',ids=ids,field='autor',operation='add',value='María Sol')['updated'],2)
        self.assertEqual(self.call('bulk_metadata',ids=ids,field='etiquetas',operation='add',value='arte')['updated'],2)
        self.assertEqual(len(self.call('query',tokens=['@autor:María Sol'])['items']),2)
        self.assertEqual(len(self.call('query',tokens=['autor:María Sol'])['items']),2)
        self.assertTrue(any(a['author']=='María Sol' and a['total']==2 for a in self.call('authors')))
        self.assertIn('Ana Torres',self.call('detail',id=ids[0])['autor'])
        self.assertIn('+historia',self.call('detail',id=ids[0])['etiquetas'])
        self.call('bulk_metadata',ids=ids,field='autor',operation='remove',value='María Sol')
        self.assertFalse(self.call('query',tokens=['autor:María Sol'])['items'])
        self.assertFalse(self.api.call('bulk_metadata',{'ids':[ids[0],'test_drive_002'],'field':'etiquetas','operation':'add','value':'seguro'})['ok'])
        self.assertNotIn('+seguro',self.call('detail',id=ids[0])['etiquetas'])
    def test_internal_search_inheritance_pin_and_recent(self):
        root=r'Mi unidad\Biblioteca\Containers\Mundodisco'
        with closing(self.api._connect()) as db:
            with db:
                db.execute("INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive,indexar_contenido) VALUES(?,?,?,?,?,1)",
                           ('test_container','Mundodisco','curso',root,'test'))
                db.execute("INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive,container_parent) VALUES(?,?,?,?,?,?)",
                           ('test_folder','Unit 3','curso',root+r'\Unit 3','test','test_container'))
                db.execute("INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive,container_parent) VALUES(?,?,?,?,?,?)",
                           ('test_mort','Mort','pdf',root+r'\Unit 3\Mort.pdf','test','test_container'))
        self.assertEqual([r['drive_id'] for r in self.call('query')['items']],['test_container','test_drive_001'])
        self.assertEqual([r['drive_id'] for r in self.call('query',tokens=['Mort'])['items']],['test_mort'])
        self.call('set_search_override',ids=['test_folder'],value=0)
        self.assertFalse(self.call('query',tokens=['Mort'])['items'])
        self.call('set_search_override',ids=['test_mort'],value=1)
        self.assertEqual([r['drive_id'] for r in self.call('query',tokens=['Mort'])['items']],['test_mort'])
        self.call('bulk_update',ids=['test_folder','test_mort'],field='es_favorito',value=True)
        self.assertTrue(self.call('detail',id='test_folder')['es_favorito'])
        self.call('bulk_update',ids=['test_mort'],field='fijado',value=True)
        self.assertEqual(self.call('query')['items'][0]['drive_id'],'test_mort')
        with closing(self.api._connect()) as db:
            with db: db.execute('UPDATE items SET ultimo_acceso=CURRENT_TIMESTAMP WHERE drive_id=?',('test_mort',))
        self.assertEqual([r['drive_id'] for r in self.call('query',tokens=['@recientes'])['items']],['test_mort'])
        self.call('remove_recent',id='test_mort')
        self.assertFalse(self.call('query',tokens=['@recientes'])['items'])
    def test_bulk_remove_recent_only_changes_active_profile(self):
        with closing(self.api._connect()) as db:
            with db:
                db.execute("INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive,ultimo_acceso) VALUES('test_recent_second','Segundo','pdf','second.pdf','test',CURRENT_TIMESTAMP)")
                db.execute("INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive,fecha_agregado,ultimo_acceso) VALUES('test_recent_third','Tercero','pdf','third.pdf','test','2020-01-01',CURRENT_TIMESTAMP)")
                db.execute("UPDATE items SET ultimo_acceso=CURRENT_TIMESTAMP WHERE drive_id='test_drive_001'")
                db.execute("UPDATE items SET ultimo_acceso=CURRENT_TIMESTAMP WHERE drive_id='test_drive_002'")
        ids=['test_drive_001','test_recent_second']
        self.assertEqual(self.call('selection_properties',ids=ids)['recent_count'],2)
        self.assertFalse(self.api.call('bulk_remove_recent',{'ids':[ids[0],'test_drive_002']})['ok'])
        self.assertEqual(self.call('selection_properties',ids=ids)['recent_count'],2)
        self.assertEqual(self.call('bulk_remove_recent',ids=ids)['updated'],2)
        self.assertEqual(self.call('selection_properties',ids=ids)['recent_count'],0)
        self.assertEqual([item['drive_id'] for item in self.call('query',tokens=['@recientes'])['items']],['test_recent_third'])
        self.assertEqual(self.call('query')['items'][0]['drive_id'],'test_recent_third')
        self.assertEqual(self.call('query',tokens=['@orden:abiertos'])['items'][0]['drive_id'],'test_recent_third')
        self.assertEqual(self.call('bulk_remove_recent',ids=ids)['updated'],0)
    def test_selection_properties_only_marks_shared_values(self):
        with closing(self.api._connect()) as db:
            with db:
                db.execute("INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive,rating,es_favorito,estado_lectura) VALUES('test_other','Otro','pdf','other.pdf','test',5,1,'abandonado')")
                db.execute("UPDATE items SET rating=5,es_favorito=1,estado_lectura='abandonado' WHERE drive_id='test_drive_001'")
        ids=['test_drive_001','test_other']
        shared=self.call('selection_properties',ids=ids)
        self.assertEqual((shared['rating'],shared['es_favorito'],shared['estado_lectura']),(5,1,'abandonado'))
        self.call('bulk_update',ids=['test_other'],field='rating',value=2)
        self.call('bulk_update',ids=['test_other'],field='es_favorito',value=False)
        self.call('bulk_update',ids=['test_other'],field='estado_lectura',value='pendiente')
        mixed=self.call('selection_properties',ids=ids)
        self.assertIsNone(mixed['rating'])
        self.assertIsNone(mixed['es_favorito'])
        self.assertIsNone(mixed['estado_lectura'])
    def test_hidden_sort_and_taxonomy_edit(self):
        with closing(self.api._connect()) as db:
            db.execute("UPDATE items SET tamano_bytes=200,fecha_agregado='2020-01-01' WHERE drive_id='test_drive_001'")
            db.execute("INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive,tamano_bytes,fecha_agregado) VALUES('test_drive_003','Grande','pdf','third.pdf','test',900,'2025-01-01')")
            db.commit()
        self.assertEqual([r['drive_id'] for r in self.call('query',tokens=['@orden:peso'])['items']],['test_drive_003','test_drive_001'])
        self.call('set_hidden',id='test_drive_003',hidden=True)
        self.assertEqual([r['drive_id'] for r in self.call('query')['items']],['test_drive_001'])
        self.assertEqual([r['drive_id'] for r in self.call('query',tokens=['@ocultos'])['items']],['test_drive_003'])
        self.call('set_hidden',id='test_drive_003',hidden=False)
        self.call('bulk_update',ids=['test_drive_003'],field='oculto',value=True)
        self.assertEqual([r['drive_id'] for r in self.call('query',tokens=['@ocultos'])['items']],['test_drive_003'])
        self.call('bulk_update',ids=['test_drive_003'],field='oculto',value=False)
        self.assertIn('test_drive_003',[r['drive_id'] for r in self.call('query')['items']])
        self.call('update',id='test_drive_001',field='etiquetas',value='+historia')
        self.assertEqual(self.call('taxonomy_edit',kind='tag',operation='rename',old='historia',new='arte')['updated'],1)
        self.assertEqual(self.call('query',tokens=['+arte'])['items'][0]['drive_id'],'test_drive_001')
        self.call('taxonomy_edit',kind='tag',operation='delete',old='arte')
        self.assertEqual(self.call('query',tokens=['+arte'])['items'],[])
    def test_assign_and_ungroup_physical_container(self):
        library=self.root/'Mi unidad'/'Biblioteca'
        folder=library/'Containers'/'Física'; folder.mkdir(parents=True)
        source=library/'book.pdf'; source.write_bytes(b'book')
        with closing(self.api._connect()) as db:
            with db:
                configurar(db,'unidad_drive:test',str(self.root))
                db.execute("UPDATE items SET ruta_relativa=? WHERE drive_id='test_drive_001'",(r'Mi unidad\Biblioteca\book.pdf',))
                db.execute("INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive) VALUES('test_container','Física','curso',?,'test')",(r'Mi unidad\Biblioteca\Containers\Física',))
        result=self.call('assign_container',ids=['test_drive_001'],container_id='test_container')
        self.assertEqual(result['moved'],1)
        self.assertTrue((folder/'book.pdf').is_file())
        self.assertEqual(self.call('query')['items'][0]['drive_id'],'test_container')
        self.assertEqual(self.call('ungroup_container',id='test_container')['released'],1)
        self.assertTrue(source.is_file())
        self.assertIn('test_drive_001',[r['drive_id'] for r in self.call('query')['items']])
    def test_move_container_folder_to_storage_preserves_file_as_library_item(self):
        library=self.root/'Mi unidad'/'Biblioteca';folder=library/'Containers'/'Course'/'Section';folder.mkdir(parents=True)
        source=folder/'lesson.pdf';source.write_bytes(b'pdf bytes')
        with closing(self.api._connect()) as db:
            with db:
                configurar(db,'unidad_drive:test',str(self.root))
                db.execute("INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive) VALUES(?,?,?,?,?)",
                           ('test_container','Course','curso',r'Mi unidad\Biblioteca\Containers\Course','test'))
                db.execute("INSERT INTO container_entries(container_drive_id,drive_id,titulo,ruta_relativa,perfil_drive) VALUES(?,?,?,?,?)",
                           ('test_container','test_lesson','lesson.pdf',r'Mi unidad\Biblioteca\Containers\Course\Section\lesson.pdf','test'))
        records={'folder_section':{'id':'folder_section','title':'Section','path':r'Mi unidad\Biblioteca\Containers\Course\Section','folder':True},
                 'test_lesson':{'id':'test_lesson','title':'Section/lesson.pdf','path':r'Mi unidad\Biblioteca\Containers\Course\Section\lesson.pdf','size':9,'mime':'application/pdf'}}
        original=self.api._dispatch
        def dispatch(db,action,payload):
            if action=='container':
                self.api._containers[payload['id']]=records
                return list(records.values())
            return original(db,action,payload)
        with patch.object(self.api,'_dispatch',side_effect=dispatch):
            result=self.call('container_move_folder_to_storage',container='test_container',path=['Section'])
        self.assertEqual(result['moved'],1)
        self.assertFalse(folder.exists())
        self.assertEqual((library/'Storage'/'Section'/'lesson.pdf').read_bytes(),b'pdf bytes')
        with closing(self.api._connect()) as db:
            item=db.execute("SELECT categoria_macro,ruta_relativa,disponible FROM items WHERE drive_id='test_lesson'").fetchone()
            self.assertEqual(tuple(item),('Storage',r'Mi unidad\Biblioteca\Storage\Section\lesson.pdf',1))
            self.assertIsNone(db.execute("SELECT 1 FROM container_entries WHERE drive_id='test_lesson'").fetchone())
            move=db.execute("SELECT expected_relative,container_drive_id FROM pending_container_moves WHERE drive_id='test_lesson'").fetchone()
            self.assertEqual(tuple(move),(r'Mi unidad\Biblioteca\Storage\Section\lesson.pdf',''))
    def test_container_view_preference_is_saved_per_container(self):
        with closing(self.api._connect()) as db:
            with db:
                db.execute("INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive) VALUES(?,?,?,?,?)",
                           ('test_container','Course','curso',r'Mi unidad\Biblioteca\Containers\Course','test'))
        self.assertEqual(self.call('container_view',id='test_container')['view'],'details')
        self.assertEqual(self.call('container_view',id='test_container',view='grid')['view'],'grid')
        self.assertEqual(self.call('container_view',id='test_container')['view'],'grid')
        self.assertEqual(self.call('container_view',id='test_container',view='list')['view'],'list')
        self.assertFalse(self.api.call('container_view',{'id':'test_container','view':'invalid'})['ok'])
    def test_container_background_preferences_are_independent_and_bounded(self):
        self.call('preference',key='wallpaper_opacity',value=31)
        self.call('preference',key='wallpaper_blur',value=12)
        self.call('preference',key='container_wallpaper',value='containers.jpg')
        self.call('preference',key='container_background_opacity',value=78)
        self.call('preference',key='container_background_blur',value=7)
        prefs=self.call('bootstrap')['prefs']
        self.assertEqual(prefs['wallpaper_opacity'],'31')
        self.assertEqual(prefs['wallpaper_blur'],'12')
        self.assertEqual(prefs['container_wallpaper'],'containers.jpg')
        self.assertEqual(prefs['container_background_opacity'],'78')
        self.assertEqual(prefs['container_background_blur'],'7')
        self.assertFalse(self.api.call('preference',{'key':'container_background_opacity','value':101})['ok'])
        self.assertFalse(self.api.call('preference',{'key':'container_background_blur','value':31})['ok'])
    def test_container_resource_properties_remain_editable_when_nested(self):
        with closing(self.api._connect()) as db:
            with db:
                db.execute("INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive,disponible) VALUES(?,?,?,?,?,1)",
                           ('test_container','Course','curso',r'Mi unidad\Biblioteca\Containers\Course','test'))
                db.execute("UPDATE items SET disponible=0 WHERE drive_id='test_drive_001'")
                db.execute("INSERT INTO container_entries(container_drive_id,drive_id,titulo,ruta_relativa,perfil_drive) VALUES(?,?,?,?,?)",
                           ('test_container','test_drive_001','Books/Book.pdf',r'Mi unidad\Biblioteca\Containers\Course\Books\Book.pdf','test'))
        original=self.api._dispatch
        def dispatch(db,action,payload):
            if action=='container':
                rows={'test_drive_001':{'id':'test_drive_001','title':'Books/Book.pdf','path':r'Mi unidad\Biblioteca\Containers\Course\Books\Book.pdf'}}
                self.api._containers[payload['id']]=rows
                return list(rows.values())
            return original(db,action,payload)
        with patch.object(self.api,'_dispatch',side_effect=dispatch):
            result=self.call('container_update',container='test_container',id='test_drive_001',field='rating',value=4)
        self.assertEqual(result,{'field':'rating','value':4})
        with closing(self.api._connect()) as db:
            self.assertEqual(tuple(db.execute("SELECT rating,disponible FROM items WHERE drive_id='test_drive_001'").fetchone()),(4,0))
    def test_create_container_and_import_folder(self):
        library=self.root/'Mi unidad'/'Biblioteca'; library.mkdir(parents=True)
        source=library/'book.pdf'; source.write_bytes(b'book')
        external=self.root/'Guías'; external.mkdir(); (external/'uno.pdf').write_bytes(b'one')
        with closing(self.api._connect()) as db:
            with db:
                configurar(db,'unidad_drive:test',str(self.root))
                db.execute("UPDATE items SET ruta_relativa=? WHERE drive_id='test_drive_001'",(r'Mi unidad\Biblioteca\book.pdf',))
        with patch('core.container_ops.drive_id_for_path',return_value='test_container_new'):
            created=self.call('assign_container',ids=['test_drive_001'],name='Nuevo')
            self.assertEqual(created['container_id'],'test_container_new')
            self.assertTrue((library/'Containers'/'Nuevo'/'book.pdf').is_file())
            imported=self.call('import_container',path=str(external))
            self.assertEqual(imported['title'],'Guías')
            self.assertTrue((library/'Containers'/'Guías'/'uno.pdf').is_file())
    def test_retry_container_creation_after_drive_metadata_delay(self):
        library=self.root/'Mi unidad'/'Biblioteca'; library.mkdir(parents=True)
        source=library/'book.pdf'; source.write_bytes(b'book')
        with closing(self.api._connect()) as db:
            with db:
                configurar(db,'unidad_drive:test',str(self.root))
        (library/'Containers'/'Pendiente').mkdir(parents=True)
        with patch('core.container_ops.drive_id_for_path',return_value='test_pending'):
            result=self.call('assign_container',ids=['test_drive_001'],name='Pendiente')
        self.assertEqual(result['moved'],1)
        self.assertTrue((library/'Containers'/'Pendiente'/'book.pdf').is_file())
    def test_similar_uses_tags_authors_then_size(self):
        with closing(self.api._connect()) as db:
            with db:
                db.execute("UPDATE items SET etiquetas='+arte',autor='Ana',tamano_bytes=1000 WHERE drive_id='test_drive_001'")
                db.execute("INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive,etiquetas,tamano_bytes) VALUES('test_drive_003','Arte','pdf','a.pdf','test','+arte',900)")
                db.execute("INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive,tamano_bytes) VALUES('test_drive_004','Tamaño','pdf','b.pdf','test',950)")
        result=self.call('similar',id='test_drive_001')
        self.assertEqual(result['ids'][0],'test_drive_001')
        self.assertEqual(result['ids'][1],'test_drive_003')
        with closing(self.api._connect()) as db:
            with db: db.execute("UPDATE items SET etiquetas='' WHERE drive_id='test_drive_003'")
        self.assertEqual(self.call('similar',id='test_drive_001')['basis'],'tamaño')
    def test_favorites_states_and_multiple_authors_persist(self):
        self.call('update',id='test_drive_001',field='autor',value='Ana Torres\nLuis Vega\nana torres')
        self.call('update',id='test_drive_001',field='es_favorito',value=1)
        self.call('update',id='test_drive_001',field='estado_lectura',value='leyendo')
        self.assertEqual(self.call('detail',id='test_drive_001')['autor'],'Ana Torres\nLuis Vega')
        self.assertEqual(len(self.call('query',tokens=['@favoritos','@leyendo'])['items']),1)
        self.assertEqual(len(self.call('query',tokens=['Luis'])['items']),1)
        self.assertEqual(len(self.call('query',tokens=['@favoritos','@pendiente'])['items']),0)
        reopened=DesktopAPI(self.root)
        self.assertEqual(reopened.call('detail',{'id':'test_drive_001'})['data']['es_favorito'],1)
        self.assertEqual(reopened.call('detail',{'id':'test_drive_001'})['data']['autor'],'Ana Torres\nLuis Vega')
        self.assertFalse(self.api.call('update',{'id':'test_drive_001','field':'es_favorito','value':2})['ok'])
        self.call('update',id='test_drive_001',field='es_favorito',value=0)
        self.assertEqual(len(self.call('query',tokens=['@favoritos'])['items']),0)
    def test_concurrent_saves(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            results=list(pool.map(lambda field:self.api.call('update',{'id':'test_drive_001','field':field,'value':field}),['autor','notas','titulo']))
        self.assertTrue(all(r['ok'] for r in results))
        item=self.call('detail',id='test_drive_001')
        for field in ('autor','notas','titulo'): self.assertEqual(item[field],field)
    def test_cover_conversion_and_validation(self):
        buf=BytesIO(); Image.new('RGBA',(50,80),(100,120,150,255)).save(buf,'PNG')
        self.call('save_cover',id='test_drive_001',data=base64.b64encode(buf.getvalue()).decode())
        self.assertTrue(self.call('cover',id='test_drive_001').startswith('data:image/jpeg;base64,'))
        with Image.open(self.root/'portadas'/'test_drive_001.jpg') as image:self.assertEqual(image.format,'JPEG')
        self.assertFalse(self.api.call('save_cover',{'id':'test_drive_001','data':'bad!'})['ok'])
        # Test query filtering with @con:miniatura and @sin:miniatura
        con_res = self.call('query', tokens=['@con:miniatura'])['items']
        self.assertTrue(any(it['drive_id'] == 'test_drive_001' for it in con_res))
        sin_res = self.call('query', tokens=['@sin:miniatura'])['items']
        self.assertFalse(any(it['drive_id'] == 'test_drive_001' for it in sin_res))
    def test_open_routes_without_launching(self):
        with patch('core.items_manager.webbrowser.open',return_value=True) as opener:
            self.call('open',id='test_drive_001',mode='web')
            opener.assert_called_once_with('https://drive.google.com/file/d/test_drive_001/view')
        self.assertFalse(self.api.call('container_open',{'container':'test_drive_001','id':'unknown'})['ok'])
    def test_course_metadata_only_and_scoped_launch(self):
        source=self.root/'drivefs.db'
        def proto(value):
            raw=value.encode(); return bytes([10,len(raw)])+raw
        with closing(sqlite3.connect(source)) as db:
            db.executescript('CREATE TABLE items(stable_id INTEGER PRIMARY KEY,local_title TEXT,is_folder INT,mime_type TEXT,file_size INT,trashed INT,proto BLOB); CREATE TABLE stable_parents(item_stable_id INT,parent_stable_id INT);')
            with db:
                for ident,title,folder,parent in [(1,'Mi unidad',1,None),(2,'Biblioteca',1,1),(3,'Curso',1,2),(4,'Tema',1,3),(5,'leccion.mp4',0,4),(6,'.oculto',1,3),(7,'secret.pdf',0,6)]:
                    db.execute('INSERT INTO items VALUES(?,?,?,?,?,?,?)',(ident,title,folder,'video/mp4',123,0,proto('course_id_'+str(ident))))
                    if parent: db.execute('INSERT INTO stable_parents VALUES(?,?)',(ident,parent))
        with closing(self.api._connect()) as db:
            with db:
                db.execute("INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive) VALUES('course_id_3','Curso','curso','Mi unidad\\Biblioteca\\Curso','test')")
                configurar(db,'unidad_drive:test',str(self.root))
        profiles=[{'id':'test','ruta_db':str(source),'tiene_biblioteca':True}]
        with patch('core.desktop_api.detectar_perfiles_drive',return_value=profiles):
            resources=self.call('container',id='course_id_3')
            self.assertEqual({row['title'] for row in resources},{'Tema','Tema/leccion.mp4'})
            self.assertTrue(self.call('detail',id='course_id_4')['disponible'])
            self.assertTrue(self.call('detail',id='course_id_5')['disponible'])
            with patch('core.desktop_api.Metadata',side_effect=AssertionError('Unchanged DriveFS was scanned twice')):
                self.assertEqual(len(self.call('container',id='course_id_3')),2)
            with patch('core.desktop_api.os.startfile',create=True) as launch:
                self.call('container_open',container='course_id_3',id='course_id_5',mode='local')
                self.assertIn('leccion.mp4',launch.call_args.args[0])
            with closing(sqlite3.connect(source)) as db:
                with db:db.execute('UPDATE items SET trashed=1 WHERE stable_id=5')
            self.assertFalse(self.api.call('container_trash',{'container':'course_id_3','id':'course_id_5'})['ok'])

    def test_preferences_validation(self):
        self.call('preference',key='tema',value='light')
        self.assertEqual(self.call('bootstrap')['prefs']['tema'],'light')
        self.call('preference',key='wallpaper_opacity',value=65)
        self.assertEqual(self.call('bootstrap')['prefs']['wallpaper_opacity'],'65')
        self.assertFalse(self.api.call('preference',{'key':'wallpaper_opacity','value':101})['ok'])
        self.call('preference',key='wallpaper_blur',value=12)
        self.assertEqual(self.call('bootstrap')['prefs']['wallpaper_blur'],'12')
        self.assertFalse(self.api.call('preference',{'key':'wallpaper_blur','value':31})['ok'])
        for key,value in [('zoom',900),('tema','bad'),('id_perfil_drive','other')]:
            self.assertFalse(self.api.call('preference',{'key':key,'value':value})['ok'])

    def test_wallpaper_operations(self):
        buf=BytesIO(); Image.new('RGB',(60,60),(30,40,50)).save(buf,'JPEG')
        res=self.call('save_wallpaper',name='custom_test.jpg',data=base64.b64encode(buf.getvalue()).decode())
        self.assertEqual(res['filename'],'custom_test.jpg')
        self.call('preference',key='wallpaper',value='custom_test.jpg')
        self.call('preference',key='container_wallpaper',value='custom_test.jpg')
        self.assertEqual(self.call('bootstrap')['prefs']['wallpaper'],'custom_test.jpg')
        data_url=self.call('get_wallpaper',filename='custom_test.jpg')
        self.assertTrue(data_url.startswith('data:image/jpeg;base64,'))
        wp_list=self.call('wallpapers_list')
        self.assertTrue(any(w['filename']=='custom_test.jpg' and w['removable'] for w in wp_list))
        self.call('set_wallpaper_centered',filename='custom_test.jpg',centered=False)
        self.assertEqual(json.loads(self.call('bootstrap')['prefs']['wallpaper_positions']),{'custom_test.jpg':False})
        self.assertFalse(next(w for w in self.call('wallpapers_list') if w['filename']=='custom_test.jpg')['centered'])
        deleted=self.call('delete_wallpaper',filename='custom_test.jpg')
        self.assertTrue(deleted['active']);self.assertTrue(deleted['activeContainer'])
        prefs=self.call('bootstrap')['prefs']
        self.assertEqual(prefs['wallpaper'],'');self.assertEqual(prefs['container_wallpaper'],'')
        self.assertIsNone(self.call('get_wallpaper',filename='custom_test.jpg'))
        self.assertFalse(self.api.call('delete_wallpaper',{'filename':'../biblioteca.db'})['ok'])

    def test_cover_save_and_delete(self):
        buf=BytesIO(); Image.new('RGB',(60,80),(200,100,50)).save(buf,'JPEG')
        b64=base64.b64encode(buf.getvalue()).decode()
        self.assertTrue(self.call('save_cover',id='test_drive_001',data=b64))
        cover_data=self.call('cover',id='test_drive_001')
        self.assertTrue(cover_data and cover_data.startswith('data:image/jpeg;base64,'))
        self.assertTrue(self.call('delete_cover',id='test_drive_001'))
        self.assertIsNone(self.call('cover',id='test_drive_001'))

    def test_rating_filter_is_exact(self):
        self.call('update',id='test_drive_001',field='rating',value=5)
        self.assertEqual(len(self.call('query',tokens=['@rating:5'])['items']),1)
        for rating in range(1,5):
            self.assertEqual(self.call('query',tokens=[f'@rating:{rating}'])['items'],[])

    def test_language_management_and_bulk(self):
        with closing(self.api._connect()) as db:
            with db:
                db.execute("INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive) VALUES('test_drive_004','Segundo en perfil','pdf',?, 'test')",(r'Mi unidad\Biblioteca\second_test.pdf',))
        langs = self.call('get_languages')['languages']
        self.assertIn('Español', langs)
        self.assertIn('Inglés', langs)
        added = self.call('add_language', name='Francés')['languages']
        self.assertIn('Francés', added)
        self.call('update', id='test_drive_001', field='idioma', value='Español')
        self.assertEqual(self.call('detail', id='test_drive_001')['idioma'], 'Español')
        self.call('bulk_update', ids=['test_drive_001', 'test_drive_004'], field='idioma', value='Inglés')
        self.assertEqual(self.call('detail', id='test_drive_001')['idioma'], 'Inglés')
        self.assertEqual(self.call('detail', id='test_drive_004')['idioma'], 'Inglés')
        props = self.call('selection_properties', ids=['test_drive_001', 'test_drive_004'])
        self.assertEqual(props['idioma'], 'Inglés')
        deleted = self.call('delete_language', name='Francés')['languages']
        self.assertNotIn('Francés', deleted)

    def test_bilingual_and_robust_search(self):
        self.call('update', id='test_drive_001', field='titulo', value='Calculus Early Transcendentals')
        self.call('update', id='test_drive_001', field='idioma', value='Inglés')
        self.call('update', id='test_drive_001', field='etiquetas', value='+diseno-personajes')

        # Bilingual search (calculo / cálculo / calculus)
        self.assertEqual(self.call('query', tokens=['calculo'])['items'][0]['drive_id'], 'test_drive_001')
        self.assertEqual(self.call('query', tokens=['cálculo'])['items'][0]['drive_id'], 'test_drive_001')
        self.assertEqual(self.call('query', tokens=['calculus'])['items'][0]['drive_id'], 'test_drive_001')

        # Robust tag search with underscores and accents
        self.assertEqual(self.call('query', tokens=['+diseno_personajes'])['items'][0]['drive_id'], 'test_drive_001')
        self.assertEqual(self.call('query', tokens=['+diseño-personajes'])['items'][0]['drive_id'], 'test_drive_001')
        self.assertEqual(self.call('query', tokens=['+diseño_personajes'])['items'][0]['drive_id'], 'test_drive_001')

        # Language search filter
        self.assertEqual(self.call('query', tokens=['@idioma:ingles'])['items'][0]['drive_id'], 'test_drive_001')

class MigrationTests(unittest.TestCase):
    def test_legacy_upgrade_preserves_notes_and_builds_author_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'biblioteca.db'
            with closing(sqlite3.connect(path)) as db:
                db.executescript("CREATE TABLE items(id INTEGER PRIMARY KEY,titulo TEXT,etiquetas TEXT,notas TEXT,categoria_macro TEXT,subcategoria TEXT); INSERT INTO items VALUES(1,'Libro','+arte','Nota original','Arte',''); CREATE VIRTUAL TABLE items_fts USING fts5(titulo,etiquetas,notas,categoria_macro,subcategoria,content='items',content_rowid='id');")
            self.assertTrue(migrate_author(path)); self.assertFalse(migrate_author(path))
            self.assertTrue(path.with_name('biblioteca.pre-autor.db').exists())
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT notas FROM items').fetchone()[0],'Nota original')
                db.execute("UPDATE items SET autor='Lauricella'")
                self.assertEqual(db.execute("SELECT rowid FROM items_fts WHERE items_fts MATCH 'Lauricella'").fetchone()[0],1)

if __name__=='__main__': unittest.main()
