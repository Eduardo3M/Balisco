from pathlib import Path
from unittest.mock import patch
import sqlite3
import tempfile
import unittest
import zipfile

from core.database import conectar, configurar, preferencia
from core.drive_sync import DriveSync
from core.tags_manager import TagsManager
from core.migrations import library_migration_preview, migrate_library_layout
from core.metadata_editor import edit_taxonomy
from core.desktop_api import DesktopAPI
from core.cover_engine import collect_batch
from core.drive_setup import status
from core.container_ops import import_library_file, import_container_folder, drive_id_for_path, ungroup_container, extract_to_library


def proto(ident):
    value=ident.encode('ascii')
    return bytes([10,len(value)])+value


class UnifiedArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.mount=Path(self.temp.name)
        self.root=self.mount/'Mi unidad'/'Archivo'/'Mi Biblioteca'
        (self.root/'ciencia'/'Curso').mkdir(parents=True)
        (self.root/'_Inbox').mkdir()
        (self.root/'ciencia'/'Uno.pdf').write_bytes(b'first')
        (self.root/'ciencia'/'Curso'/'Leccion.pdf').write_bytes(b'lesson')
        (self.root/'_Inbox'/'Suelto.pdf').write_bytes(b'loose')
        self.source=self.mount/'metadata_sqlite_db'
        with sqlite3.connect(self.source) as meta:
            meta.executescript('CREATE TABLE items(stable_id INTEGER PRIMARY KEY,local_title TEXT,is_folder INT,mime_type TEXT,file_size INT,trashed INT,proto BLOB);CREATE TABLE stable_parents(item_stable_id INT,parent_stable_id INT);')
            for stable,title,folder,parent,size in (
                (1,'Mi unidad',1,None,0),(2,'Archivo',1,1,0),(3,'Mi Biblioteca',1,2,0),
                (4,'ciencia',1,3,0),(5,'Uno.pdf',0,4,5),(6,'Curso',1,4,0),
                (7,'Leccion.pdf',0,6,6),(8,'_Inbox',1,3,0),(9,'Suelto.pdf',0,8,5)):
                meta.execute('INSERT INTO items VALUES(?,?,?,?,?,?,?)',(stable,title,folder,'application/pdf',size,0,proto('drive_id_'+str(stable).zfill(3))))
                if parent:meta.execute('INSERT INTO stable_parents VALUES(?,?)',(stable,parent))
        meta.close()
        self.db=conectar(self.mount/'biblioteca.db')
        with self.db:
            configurar(self.db,'unidad_drive:fixture',str(self.mount))
            configurar(self.db,'biblioteca_root_id:fixture','drive_id_003')
            configurar(self.db,'id_perfil_drive','fixture')
        self.sync=DriveSync(self.db)
        self.profile_patch=patch('core.drive_sync.detectar_perfiles_drive',return_value=[{'id':'fixture','ruta_db':str(self.source),'tiene_biblioteca':True}])
        self.profile_patch.start()
        self.run_sync()

    def tearDown(self):
        self.profile_patch.stop();self.db.close();self.temp.cleanup()

    def run_sync(self):
        return self.sync.sincronizar_biblioteca(ruta_db=self.source,perfil='fixture')

    def test_relative_levels_and_primary_tags(self):
        rows={row['drive_id']:row for row in self.db.execute('SELECT * FROM items')}
        self.assertEqual(rows['drive_id_005']['etiquetas'],'+ciencia')
        self.assertEqual(rows['drive_id_006']['tipo'],'curso')
        self.assertEqual(rows['drive_id_007']['container_parent'],'drive_id_006')
        self.assertEqual(rows['drive_id_009']['etiquetas'],'')
        self.assertEqual(rows['drive_id_005']['categoria_macro'],'ciencia')

    def test_reordering_tags_moves_file_and_removes_empty_category(self):
        (self.root/'ciencia'/'Curso').rename(self.root/'_Inbox'/'Curso')
        with self.db:self.db.execute("UPDATE items SET ruta_relativa=?,categoria_macro='_Inbox' WHERE drive_id='drive_id_006'",(r'Mi unidad\Archivo\Mi Biblioteca\_Inbox\Curso',))
        TagsManager(self.db).actualizar_etiquetas_item('drive_id_005','+arte +ciencia +historia')
        self.assertTrue((self.root/'arte'/'Uno.pdf').is_file())
        self.assertFalse((self.root/'ciencia').exists())
        item=self.db.execute("SELECT etiquetas,ruta_relativa FROM items WHERE drive_id='drive_id_005'").fetchone()
        self.assertEqual(item['etiquetas'],'+arte +ciencia +historia')
        self.assertIn(r'arte\Uno.pdf',item['ruta_relativa'])

    def test_external_move_changes_first_tag_without_losing_others(self):
        with self.db:self.db.execute("UPDATE items SET etiquetas='+ciencia +historia' WHERE drive_id='drive_id_005'")
        (self.root/'arte').mkdir()
        (self.root/'ciencia'/'Uno.pdf').rename(self.root/'arte'/'Uno.pdf')
        with sqlite3.connect(self.source) as meta:
            meta.execute("INSERT INTO items VALUES(10,'arte',1,'application/pdf',0,0,?)",(proto('drive_id_010'),))
            meta.execute('INSERT INTO stable_parents VALUES(10,3)')
            meta.execute('UPDATE stable_parents SET parent_stable_id=10 WHERE item_stable_id=5')
        meta.close()
        self.run_sync()
        item=self.db.execute("SELECT etiquetas,ruta_relativa FROM items WHERE drive_id='drive_id_005'").fetchone()
        self.assertEqual(item['etiquetas'],'+arte +ciencia +historia')
        self.assertIn(r'arte\Uno.pdf',item['ruta_relativa'])

    def test_stale_drive_metadata_does_not_undo_a_tag_move(self):
        TagsManager(self.db).actualizar_etiquetas_item('drive_id_005','+arte +ciencia')
        self.run_sync()
        item=self.db.execute("SELECT etiquetas,ruta_relativa,disponible FROM items WHERE drive_id='drive_id_005'").fetchone()
        self.assertEqual(item['etiquetas'],'+arte +ciencia')
        self.assertIn(r'arte\Uno.pdf',item['ruta_relativa'])
        self.assertEqual(item['disponible'],1)

    def test_global_tag_rename_and_delete_move_physical_items(self):
        with self.db:self.db.execute("UPDATE items SET etiquetas='+ciencia +historia' WHERE drive_id='drive_id_005'")
        edit_taxonomy(self.db,'fixture','tag','rename','ciencia','arte')
        self.assertTrue((self.root/'arte'/'Uno.pdf').is_file())
        self.assertTrue((self.root/'arte'/'Curso').is_dir())
        self.assertEqual(self.db.execute("SELECT etiquetas FROM items WHERE drive_id='drive_id_005'").fetchone()[0],'+arte +historia')
        edit_taxonomy(self.db,'fixture','tag','delete','arte')
        self.assertTrue((self.root/'historia'/'Uno.pdf').is_file())
        self.assertTrue((self.root/'_Inbox'/'Curso').is_dir())
        self.assertFalse((self.root/'arte').exists())

    def test_global_rename_checks_all_collisions_before_moving(self):
        (self.root/'arte').mkdir();(self.root/'arte'/'Uno.pdf').write_bytes(b'other')
        with self.assertRaises(FileExistsError):
            edit_taxonomy(self.db,'fixture','tag','rename','ciencia','arte')
        self.assertTrue((self.root/'ciencia'/'Uno.pdf').is_file())
        self.assertTrue((self.root/'ciencia'/'Curso').is_dir())
        self.assertEqual(self.db.execute("SELECT etiquetas FROM items WHERE drive_id='drive_id_005'").fetchone()[0],'+ciencia')

    def test_bulk_primary_preserves_each_items_other_tags(self):
        api=DesktopAPI(self.mount)
        result=api.call('bulk_metadata',{'ids':['drive_id_005','drive_id_009'],'field':'etiquetas','operation':'add','value':'arte'})
        self.assertTrue(result['ok'],result)
        self.assertEqual(self.db.execute("SELECT etiquetas FROM items WHERE drive_id='drive_id_005'").fetchone()[0],'+ciencia +arte')
        self.assertEqual(self.db.execute("SELECT etiquetas FROM items WHERE drive_id='drive_id_009'").fetchone()[0],'+arte')
        result=api.call('bulk_metadata',{'ids':['drive_id_005','drive_id_009'],'field':'etiquetas','operation':'set','value':'historia'})
        self.assertTrue(result['ok'],result)
        self.assertEqual(self.db.execute("SELECT etiquetas FROM items WHERE drive_id='drive_id_005'").fetchone()[0],'+historia +ciencia +arte')
        self.assertEqual(self.db.execute("SELECT etiquetas FROM items WHERE drive_id='drive_id_009'").fetchone()[0],'+historia +arte')
        self.assertTrue((self.root/'historia'/'Uno.pdf').is_file())
        self.assertTrue((self.root/'historia'/'Suelto.pdf').is_file())

    def test_reupload_in_another_category_keeps_metadata_by_fingerprint(self):
        with self.db:self.db.execute("UPDATE items SET notas='Apuntes únicos' WHERE drive_id='drive_id_005'")
        (self.root/'ciencia'/'Uno.pdf').unlink()
        (self.root/'arte').mkdir();(self.root/'arte'/'Uno.pdf').write_bytes(b'first')
        with sqlite3.connect(self.source) as meta:
            meta.execute('UPDATE items SET trashed=1 WHERE stable_id=5')
            meta.execute("INSERT INTO items VALUES(10,'arte',1,'application/pdf',0,0,?)",(proto('drive_id_010'),))
            meta.execute('INSERT INTO stable_parents VALUES(10,3)')
            meta.execute("INSERT INTO items VALUES(11,'Uno.pdf',0,'application/pdf',5,0,?)",(proto('drive_id_011'),))
            meta.execute('INSERT INTO stable_parents VALUES(11,10)')
        meta.close()
        self.run_sync()
        item=self.db.execute("SELECT notas,etiquetas FROM items WHERE drive_id='drive_id_011'").fetchone()
        self.assertEqual((item['notas'],item['etiquetas']),('Apuntes únicos','+arte +ciencia'))

    def test_colab_batch_imports_only_profile_ids(self):
        from PIL import Image
        from io import BytesIO
        hidden=self.root/'.balisco';hidden.mkdir()
        data=BytesIO();Image.new('RGB',(12,16),'green').save(data,'JPEG')
        with zipfile.ZipFile(hidden/'portadas_lote.zip','w') as batch:
            batch.writestr('drive_id_005.jpg',data.getvalue())
        result=collect_batch(self.db,'fixture',self.mount)
        self.assertEqual(result['imported'],1)
        self.assertTrue((self.mount/'portadas'/'drive_id_005.jpg').is_file())
        self.assertFalse((hidden/'portadas_lote.zip').exists())

    def test_import_uses_active_filter_category_or_inbox(self):
        incoming=self.mount/'incoming';incoming.mkdir()
        (incoming/'Nuevo.pdf').write_bytes(b'new')
        (incoming/'Curso nuevo').mkdir();(incoming/'Curso nuevo'/'Tema.pdf').write_bytes(b'theme')
        import_library_file(self.db,'fixture',incoming/'Nuevo.pdf',active_tag='+historia')
        import_container_folder(self.db,'fixture',incoming/'Curso nuevo')
        self.assertTrue((self.root/'historia'/'Nuevo.pdf').is_file())
        self.assertTrue((self.root/'_Inbox'/'Curso nuevo'/'Tema.pdf').is_file())

    def test_hidden_colab_notebook_can_be_found_by_drive_id(self):
        with sqlite3.connect(self.source) as meta:
            meta.execute("INSERT INTO items VALUES(10,'.balisco',1,'folder',0,0,?)",(proto('drive_id_010'),))
            meta.execute('INSERT INTO stable_parents VALUES(10,3)')
            meta.execute("INSERT INTO items VALUES(11,'generar_portadas.ipynb',0,'application/json',10,0,?)",(proto('drive_id_011'),))
            meta.execute('INSERT INTO stable_parents VALUES(11,10)')
        meta.close()
        profiles=[{'id':'fixture','ruta_db':str(self.source),'tiene_biblioteca':True}]
        with patch('core.container_ops.detectar_perfiles_drive',return_value=profiles):
            ident=drive_id_for_path('fixture',r'Mi unidad\Archivo\Mi Biblioteca\.balisco\generar_portadas.ipynb',timeout=0,allow_hidden=True)
        self.assertEqual(ident,'drive_id_011')

    def test_ungroup_keeps_internal_file_metadata_in_same_category(self):
        with self.db:self.db.execute("UPDATE items SET notas='Nota del curso' WHERE drive_id='drive_id_007'")
        result=ungroup_container(self.db,'fixture','drive_id_006')
        self.assertEqual(result['released'],1)
        self.assertTrue((self.root/'ciencia'/'Leccion.pdf').is_file())
        item=self.db.execute("SELECT notas,etiquetas,container_parent,ruta_relativa FROM items WHERE drive_id='drive_id_007'").fetchone()
        self.assertEqual((item['notas'],item['etiquetas'],item['container_parent']),('Nota del curso','+ciencia',''))
        self.assertIn(r'ciencia\Leccion.pdf',item['ruta_relativa'])

    def test_extract_nested_folder_becomes_atomic_container(self):
        nested=self.root/'ciencia'/'Curso'/'Unidad';nested.mkdir()
        (nested/'Material.pdf').write_bytes(b'file')
        with sqlite3.connect(self.source) as meta:
            meta.execute("INSERT INTO items VALUES(10,'Unidad',1,'folder',0,0,?)",(proto('drive_id_010'),))
            meta.execute('INSERT INTO stable_parents VALUES(10,6)')
            meta.execute("INSERT INTO items VALUES(11,'Material.pdf',0,'application/pdf',4,0,?)",(proto('drive_id_011'),))
            meta.execute('INSERT INTO stable_parents VALUES(11,10)')
        meta.close()
        self.run_sync()
        with self.db:self.db.execute("UPDATE items SET notas='Dato interno' WHERE drive_id='drive_id_011'")
        container=dict(self.db.execute("SELECT * FROM items WHERE drive_id='drive_id_006'").fetchone())
        result=extract_to_library(self.db,'fixture',container,[nested])
        self.assertEqual(result['released'],1)
        self.assertTrue((self.root/'ciencia'/'Unidad'/'Material.pdf').is_file())
        folder=self.db.execute("SELECT tipo,container_parent,etiquetas FROM items WHERE drive_id='drive_id_010'").fetchone()
        file=self.db.execute("SELECT notas,container_parent,ruta_relativa FROM items WHERE drive_id='drive_id_011'").fetchone()
        self.assertEqual(tuple(folder),('curso','','+ciencia'))
        self.assertEqual((file['notas'],file['container_parent']),('Dato interno','drive_id_010'))
        self.assertIn(r'ciencia\Unidad\Material.pdf',file['ruta_relativa'])
        self.run_sync()
        stale=self.db.execute("SELECT disponible,container_parent,ruta_relativa FROM items WHERE drive_id='drive_id_011'").fetchone()
        self.assertEqual((stale['disponible'],stale['container_parent']),(1,'drive_id_010'))
        self.assertIn(r'ciencia\Unidad\Material.pdf',stale['ruta_relativa'])

    def test_root_rename_is_followed_by_drive_id(self):
        renamed=self.root.with_name('Biblioteca Renombrada')
        self.root.rename(renamed)
        with sqlite3.connect(self.source) as meta:meta.execute("UPDATE items SET local_title='Biblioteca Renombrada' WHERE stable_id=3")
        meta.close()
        self.run_sync()
        path=self.db.execute("SELECT ruta_relativa FROM items WHERE drive_id='drive_id_005'").fetchone()[0]
        self.assertIn('Biblioteca Renombrada',path)
        self.assertEqual(preferencia(self.db,'biblioteca_root_id:fixture'),'drive_id_003')

    def test_removed_root_unlinks_and_keeps_metadata(self):
        with sqlite3.connect(self.source) as meta:meta.execute('UPDATE items SET trashed=1 WHERE stable_id=3')
        meta.close()
        with self.assertRaises(ValueError):self.run_sync()
        self.assertIsNone(preferencia(self.db,'biblioteca_root_id:fixture'))
        self.assertEqual(self.db.execute("SELECT disponible FROM items WHERE drive_id='drive_id_005'").fetchone()[0],0)

    def test_setup_states_follow_drive_then_linked_root(self):
        with patch('core.drive_setup.drive_executable',return_value=None):
            self.assertEqual(status(self.db)['state'],'not_installed')
        with patch('core.drive_setup.drive_executable',return_value=Path('GoogleDriveFS.exe')),patch('core.drive_setup.drive_running',return_value=False):
            self.assertEqual(status(self.db)['state'],'not_running')
        with patch('core.drive_setup.drive_executable',return_value=Path('GoogleDriveFS.exe')),patch('core.drive_setup.drive_running',return_value=True),patch('core.drive_setup.detectar_perfiles_drive',return_value=[]):
            self.assertEqual(status(self.db)['state'],'not_running')
        profiles=[{'id':'fixture','ruta_db':str(self.source),'tiene_biblioteca':True}]
        with patch('core.drive_setup.drive_executable',return_value=Path('GoogleDriveFS.exe')),patch('core.drive_setup.drive_running',return_value=True),patch('core.drive_setup.detectar_perfiles_drive',return_value=profiles):
            self.assertEqual(status(self.db)['state'],'ready')
            with self.db:self.db.execute("DELETE FROM configuracion WHERE clave='biblioteca_root_id:fixture'")
            self.assertEqual(status(self.db)['state'],'needs_location')

    def test_legacy_migration_is_previewed_and_backed_up(self):
        (self.root/'storage').mkdir();(self.root/'containers').mkdir()
        (self.root/'storage'/'Antiguo.pdf').write_bytes(b'old')
        (self.root/'containers'/'Curso antiguo').mkdir()
        (self.root/'containers'/'Curso antiguo'/'Tema.pdf').write_bytes(b'theme')
        with self.db:
            configurar(self.db,'migration_pending:fixture','1')
            self.db.execute("INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive,etiquetas) VALUES('drive_old_001','Antiguo','pdf',?,'fixture','+historia +arte')",(r'Mi unidad\Archivo\Mi Biblioteca\storage\Antiguo.pdf',))
        preview=library_migration_preview(self.db,'fixture')
        self.assertEqual(preview['count'],2)
        result=migrate_library_layout(self.db,'fixture')
        self.assertEqual(result['moved'],2)
        self.assertTrue(Path(result['backup']).is_file())
        self.assertTrue((self.root/'historia'/'Antiguo.pdf').is_file())
        self.assertTrue((self.root/'_Inbox'/'Curso antiguo'/'Tema.pdf').is_file())
        self.assertFalse((self.root/'storage').exists())
        self.assertFalse((self.root/'containers').exists())
        self.assertIsNone(preferencia(self.db,'migration_pending:fixture'))

    def test_profile_storage_isolates_accounts_and_migrates_legacy_db(self):
        from core.profile_storage import ProfileStorage
        from core.thumbnailer import thumbnail_name
        base=self.mount/'local_balisco'
        base.mkdir()
        with sqlite3.connect(base/'biblioteca.db') as legacy:
            legacy.close()
        legacy_db=conectar(base/'biblioteca.db')
        with legacy_db:
            configurar(legacy_db,'id_perfil_drive','account_A')
            configurar(legacy_db,'biblioteca_root_id:account_A','root_A')
            configurar(legacy_db,'biblioteca_root_id:account_B','root_B')
            legacy_db.execute("INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive,notas) VALUES('doc_a','Libro A','pdf','Mi unidad\\BibA\\a.pdf','account_A','Nota A')")
            legacy_db.execute("INSERT INTO items(drive_id,titulo,tipo,ruta_relativa,perfil_drive,notas) VALUES('doc_b','Libro B','pdf','Mi unidad\\BibB\\b.pdf','account_B','Nota B')")
        legacy_db.close()
        (base/'portadas').mkdir()
        (base/'portadas'/'doc_a.jpg').write_bytes(b'cover_a')
        (base/'portadas'/'doc_b.jpg').write_bytes(b'cover_b')
        (base/'portadas_auto').mkdir()
        (base/'portadas_auto'/thumbnail_name('account_A','Mi unidad\\BibA\\a.pdf')).write_bytes(b'auto_a')
        (base/'portadas_auto'/thumbnail_name('account_B','Mi unidad\\BibB\\b.pdf')).write_bytes(b'auto_b')

        storage=ProfileStorage(base)
        self.assertEqual(storage.active,'account_A')
        self.assertTrue((base/'perfiles'/'account_A'/'biblioteca.db').is_file())
        self.assertTrue((base/'perfiles'/'account_A'/'portadas'/'doc_a.jpg').is_file())
        self.assertFalse((base/'perfiles'/'account_A'/'portadas'/'doc_b.jpg').exists())
        self.assertTrue((base/'perfiles'/'account_B'/'biblioteca.db').is_file())
        self.assertTrue((base/'perfiles'/'account_B'/'portadas'/'doc_b.jpg').is_file())
        self.assertFalse((base/'perfiles'/'account_B'/'portadas'/'doc_a.jpg').exists())

        # New third account starts completely empty in its own directory
        storage.activate('account_C')
        self.assertEqual(storage.active,'account_C')
        with conectar(storage.database('account_C')) as db_c:
            self.assertEqual(db_c.execute('SELECT count(*) FROM items').fetchone()[0],0)
            self.assertEqual(preferencia(db_c,'id_perfil_drive'),'account_C')


if __name__=='__main__':unittest.main()
