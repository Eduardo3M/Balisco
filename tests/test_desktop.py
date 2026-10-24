import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from io import BytesIO
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
        self.assertEqual(len(self.call('query',tokens=['autor:María Sol'])['items']),2)
        self.assertTrue(any(a['author']=='María Sol' and a['total']==2 for a in self.call('authors')))
        self.assertIn('Ana Torres',self.call('detail',id=ids[0])['autor'])
        self.assertIn('+historia',self.call('detail',id=ids[0])['etiquetas'])
        self.call('bulk_metadata',ids=ids,field='autor',operation='remove',value='María Sol')
        self.assertFalse(self.call('query',tokens=['autor:María Sol'])['items'])
        self.assertFalse(self.api.call('bulk_metadata',{'ids':[ids[0],'test_drive_002'],'field':'etiquetas','operation':'add','value':'seguro'})['ok'])
        self.assertNotIn('+seguro',self.call('detail',id=ids[0])['etiquetas'])
    def test_favorites_states_and_multiple_authors_persist(self):
        self.call('update',id='test_drive_001',field='autor',value='Ana Torres\nLuis Vega\nana torres')
        self.call('update',id='test_drive_001',field='es_favorito',value=1)
        self.call('update',id='test_drive_001',field='estado_lectura',value='leyendo')
        self.assertEqual(self.call('detail',id='test_drive_001')['autor'],'Ana Torres\nLuis Vega')
        self.assertEqual(len(self.call('query',tokens=['@favoritos','@leyendo'])['items']),1)
        self.assertEqual(len(self.call('query',tokens=['Luis'])['items']),1)
        self.assertEqual(len(self.call('query',tokens=['@favoritos','@pendiente'])['items']),1)
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
    def test_open_routes_without_launching(self):
        with patch('core.items_manager.webbrowser.open',return_value=True) as opener:
            self.call('open',id='test_drive_001',mode='web')
            opener.assert_called_once_with('https://drive.google.com/file/d/test_drive_001/view')
        self.assertFalse(self.api.call('course_open',{'course':'test_drive_001','id':'unknown'})['ok'])
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
            resources=self.call('course',id='course_id_3')
            self.assertEqual(len(resources),1);self.assertEqual(resources[0]['title'],'Tema / leccion.mp4')
            with patch('core.desktop_api.os.startfile',create=True) as launch:
                self.call('course_open',course='course_id_3',id='course_id_5',mode='local')
                self.assertIn('leccion.mp4',launch.call_args.args[0])
            with closing(sqlite3.connect(source)) as db:
                with db:db.execute('UPDATE items SET trashed=1 WHERE stable_id=5')
            self.assertFalse(self.api.call('course_trash',{'course':'course_id_3','id':'course_id_5'})['ok'])

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
        try:
            buf=BytesIO(); Image.new('RGB',(60,60),(30,40,50)).save(buf,'JPEG')
            res=self.call('save_wallpaper',name='custom_test.jpg',data=base64.b64encode(buf.getvalue()).decode())
            self.assertEqual(res['filename'],'custom_test.jpg')
            self.call('preference',key='wallpaper',value='custom_test.jpg')
            self.assertEqual(self.call('bootstrap')['prefs']['wallpaper'],'custom_test.jpg')
            data_url=self.call('get_wallpaper',filename='custom_test.jpg')
            self.assertTrue(data_url.startswith('data:image/jpeg;base64,'))
            wp_list=self.call('wallpapers_list')
            self.assertTrue(any(w['filename']=='custom_test.jpg' for w in wp_list))
        finally:
            (Path(__file__).parent.parent/'wallpapers'/'custom_test.jpg').unlink(missing_ok=True)

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
